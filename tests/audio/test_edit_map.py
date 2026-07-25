from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from larp_audio_mvp.audio.edit_map_builder import EditMapBuilder
from larp_audio_mvp.audio.pause_policy import PauseShorteningPolicy
from larp_audio_mvp.audio.serialization import (
    edit_map_from_dict,
    edit_map_to_dict,
    read_edit_map,
    write_edit_map_atomic,
)
from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo, EditKind, PauseSegment
from larp_audio_mvp.core.timeline import TimelineMapper
from larp_audio_mvp.core.errors import EditMapError


def _policy() -> PauseShorteningPolicy:
    return PauseShorteningPolicy(
        PauseSettings(
            shortening_policy_version="test-v1",
            minimum_pause_to_shorten_ms=1_500,
            target_remaining_pause_ms=1_000,
            maximum_removed_per_pause_ms=1_000,
        )
    )


def _audio(path: Path, total_samples: int = 10_000) -> AudioInfo:
    return AudioInfo(
        source_path=path,
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=1_000,
        channels=1,
        sample_format="s16",
        total_samples=total_samples,
        stream_index=0,
        is_canonical=True,
        sha256="source-hash",
    )


def _map(tmp_path: Path):
    policy = _policy()
    pauses = [
        PauseSegment(2_000, 4_000, 1_000),
        PauseSegment(6_000, 8_000, 1_000),
    ]
    decisions = policy.decide(pauses, total_samples=10_000, sample_rate=1_000)
    return EditMapBuilder().build(_audio(tmp_path / "source.wav"), decisions, policy=policy)


def test_builder_creates_complete_partition_and_removed_totals(tmp_path: Path) -> None:
    edit_map = _map(tmp_path)

    assert edit_map.source_total_samples == 10_000
    assert edit_map.output_total_samples == 8_000
    assert edit_map.removed_samples == 2_000
    assert [span.kind for span in edit_map.spans] == [
        EditKind.KEEP,
        EditKind.REMOVE,
        EditKind.KEEP,
        EditKind.REMOVE,
        EditKind.KEEP,
    ]
    removals = [span for span in edit_map.spans if span.kind is EditKind.REMOVE]
    assert [span.removed_samples for span in removals] == [1_000, 1_000]
    assert [(span.target_start, span.target_end) for span in removals] == [
        (2_500, 2_500),
        (5_500, 5_500),
    ]


def test_identity_map_has_one_keep_span_and_no_drift(tmp_path: Path) -> None:
    policy = _policy()
    edit_map = EditMapBuilder().build(
        _audio(tmp_path / "source.wav"),
        (),
        policy=policy,
    )

    assert edit_map.removed_samples == 0
    assert edit_map.output_total_samples == edit_map.source_total_samples
    assert len(edit_map.spans) == 1
    mapper = TimelineMapper(edit_map)
    for sample in (0, 1, 5_000, 9_999, 10_000):
        assert mapper.source_to_target(sample) == sample
        assert mapper.target_to_source(sample) == sample


def test_mapper_collapses_removed_samples_and_inverts_kept_samples(
    tmp_path: Path,
) -> None:
    edit_map = _map(tmp_path)
    mapper = TimelineMapper(edit_map)

    assert mapper.source_to_target(2_499) == 2_499
    assert mapper.source_to_target(2_500) == 2_500
    assert mapper.source_to_target(3_000) == 2_500
    assert mapper.source_to_target(3_499) == 2_500
    assert mapper.source_to_target(3_500) == 2_500
    assert mapper.target_to_source(2_499) == 2_499
    assert mapper.target_to_source(2_500) == 3_500
    assert mapper.source_to_target(7_000) == 5_500
    assert mapper.source_to_target(7_499) == 5_500
    assert mapper.target_to_source(5_500) == 7_500

    for source_sample in range(edit_map.source_total_samples):
        if any(
            span.kind is EditKind.REMOVE
            and span.source_start <= source_sample < span.source_end
            for span in edit_map.spans
        ):
            continue
        target = mapper.source_to_target(source_sample)
        assert mapper.target_to_source(target) == source_sample


def test_mapper_uses_binary_search_for_each_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edit_map = _map(tmp_path)
    import larp_audio_mvp.core.timeline as timeline_module

    calls = 0
    original = timeline_module.bisect_right

    def counting_bisect(values: tuple[int, ...], value: int) -> int:
        nonlocal calls
        calls += 1
        return original(values, value)

    monkeypatch.setattr(timeline_module, "bisect_right", counting_bisect)
    mapper = TimelineMapper(edit_map)

    assert mapper.source_to_target(9_000) == 7_000
    assert mapper.target_to_source(7_000) == 9_000
    assert calls == 2


def test_edit_map_serialization_is_stable_and_atomic(tmp_path: Path) -> None:
    edit_map = replace(_map(tmp_path), output_sha256="target-hash")
    destination = tmp_path / "edit map ü.json"

    write_edit_map_atomic(edit_map, destination)
    first = destination.read_bytes()
    write_edit_map_atomic(edit_map, destination)
    second = destination.read_bytes()
    payload = json.loads(second)

    assert first == second
    assert payload == edit_map_to_dict(edit_map)
    assert payload["audio"]["removed_samples"] == 2_000
    assert payload["spans"][1]["source_start"] == 2_500
    assert payload["spans"][1]["target_start"] == 2_500
    assert payload["spans"][1]["removed_samples"] == 1_000
    assert list(tmp_path.glob("*.partial.json")) == []
    assert hashlib.sha256(first).hexdigest()
    assert edit_map_to_dict(edit_map_from_dict(payload)) == payload
    assert edit_map_to_dict(read_edit_map(destination)) == payload


def test_many_cuts_have_no_cumulative_rounding_error(tmp_path: Path) -> None:
    policy = PauseShorteningPolicy(
        PauseSettings(
            shortening_policy_version="dense-v1",
            minimum_pause_to_shorten_ms=3,
            target_remaining_pause_ms=2,
            maximum_removed_per_pause_ms=8,
        )
    )
    total_samples = 3_000
    pauses = [
        PauseSegment(start, start + 10, 1_000)
        for start in range(10, 2_010, 20)
    ]
    audio = _audio(tmp_path / "dense.wav", total_samples=total_samples)
    decisions = policy.decide(
        pauses,
        total_samples=total_samples,
        sample_rate=1_000,
    )
    edit_map = EditMapBuilder().build(audio, decisions, policy=policy)
    mapper = TimelineMapper(edit_map)

    assert len(pauses) == 100
    assert edit_map.removed_samples == 800
    assert edit_map.output_total_samples == 2_200
    assert mapper.source_to_target(2_500) == 1_700
    assert mapper.target_to_source(1_700) == 2_500


def test_edit_map_reader_rejects_tampered_redundant_sample_count(
    tmp_path: Path,
) -> None:
    edit_map = replace(_map(tmp_path), output_sha256="target-hash")
    payload = deepcopy(edit_map_to_dict(edit_map))
    payload["audio"]["removed_samples"] += 1
    destination = tmp_path / "tampered.json"
    destination.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EditMapError) as captured:
        read_edit_map(destination)

    assert captured.value.code == "INVALID_EDIT_MAP"
