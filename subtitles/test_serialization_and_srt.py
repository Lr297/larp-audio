from __future__ import annotations

import codecs
import hashlib
import json
from pathlib import Path
from typing import Callable

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult
from larp_audio_mvp.core.errors import (
    SubtitleExportError,
    SubtitleSerializationError,
    SubtitleTimingError,
    SubtitleValidationError,
)
from larp_audio_mvp.exports import (
    SrtExporter,
    render_srt,
    subtitle_cues,
    validate_srt,
)
from larp_audio_mvp.subtitles import (
    DeterministicSubtitleChunker,
    read_subtitle_document,
    subtitle_document_to_dict,
    write_subtitle_document,
)


def _document(
    alignment: AlignmentResult, settings: SubtitleSettings | None = None
):
    return DeterministicSubtitleChunker().chunk(
        alignment,
        settings=settings or SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"alignment fixture").hexdigest(),
    )


def test_json_roundtrip_is_atomic_unicode_and_deterministic(
    alignment_factory: Callable[..., AlignmentResult], tmp_path: Path
) -> None:
    document = _document(
        alignment_factory("Привіт, žltý svet!\r\nEmoji 😀 zostáva.", bom=True),
        SubtitleSettings(),
    )
    destination = tmp_path / "subtitle blocks ü.json"
    write_subtitle_document(document, destination)
    first = destination.read_bytes()
    restored = read_subtitle_document(destination)
    write_subtitle_document(restored, destination)

    assert destination.read_bytes() == first
    assert subtitle_document_to_dict(restored) == subtitle_document_to_dict(document)
    assert json.loads(first)["script"]["exact_text"] == document.exact_script_text
    assert first.endswith(b"\n")
    assert not list(tmp_path.glob("*.partial.json"))


def _write_corrupt(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "diagnostics",
        "char_span",
        "script_hash",
        "missing_word",
        "duplicate_word",
        "block_index",
        "cps",
        "provenance",
        "display_text",
        "denominator",
        "timing_range",
    ],
)
def test_strict_reader_rejects_corruption_with_controlled_error(
    alignment_factory: Callable[..., AlignmentResult],
    tmp_path: Path,
    mutation: str,
) -> None:
    document = _document(
        alignment_factory("one missing world", missing_indices=(1,))
    )
    payload = subtitle_document_to_dict(document)
    block = payload["blocks"][0]
    if mutation == "schema":
        payload["schema_version"] = "subtitle_blocks.schema.unknown"
    elif mutation == "diagnostics":
        payload["diagnostics"]["total_blocks"] = 999
    elif mutation == "char_span":
        block["source_char_start"] = 1
    elif mutation == "script_hash":
        payload["script"]["source_sha256"] = "0" * 64
    elif mutation == "missing_word":
        block["script_word_indices"].pop()
        block["word_count"] -= 1
    elif mutation == "duplicate_word":
        block["script_word_indices"].append(block["script_word_indices"][-1])
        block["word_count"] += 1
    elif mutation == "block_index":
        block["block_index"] = 2
    elif mutation == "cps":
        block["characters_per_second"]["numerator"] += 1
    elif mutation == "provenance":
        block = next(
            item
            for item in payload["blocks"]
            if item["contains_interpolated_words"]
        )
        block["timing_provenance"] = "observed"
    elif mutation == "display_text":
        block["display_lines"][0] += " ASR"
    elif mutation == "denominator":
        payload["diagnostics"]["text_coverage"]["denominator"] = 0
    elif mutation == "timing_range":
        block["cleaned_end_sample"] = payload["cleaned_total_samples"] + 1
        block["duration_samples"] = (
            block["cleaned_end_sample"] - block["cleaned_start_sample"]
        )
    source = _write_corrupt(tmp_path, payload, mutation)
    with pytest.raises((SubtitleSerializationError, SubtitleValidationError)):
        read_subtitle_document(source)


def test_json_writer_cleans_partial_after_failure(
    alignment_factory: Callable[..., AlignmentResult],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document(alignment_factory("hello world"))
    import larp_audio_mvp.subtitles.serialization as module

    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(SubtitleSerializationError):
        write_subtitle_document(document, tmp_path / "blocks.json")
    assert not list(tmp_path.glob("*.partial.json"))


def test_srt_uses_crlf_cleaned_timeline_and_exact_display_lines(
    alignment_factory: Callable[..., AlignmentResult]
) -> None:
    document = _document(
        alignment_factory("hello. world.", word_starts=(1_234, 2_345), word_duration=321),
    )
    payload = render_srt(document)
    text = payload.decode("utf-8")
    assert not payload.startswith(codecs.BOM_UTF8)
    assert "\r\n\r\n" in text
    assert "\n" not in text.replace("\r\n", "")
    assert "00:00:01,234 --> 00:00:02,344" in text
    assert [cue.index for cue in subtitle_cues(document)] == [1, 2]
    validate_srt(payload, document)


def test_srt_continuity_preserves_speech_end_and_uses_next_start_minus_one_ms(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(
        alignment_factory(
            "first. second.",
            word_starts=(1_000, 4_800),
            word_duration=455,
            sample_rate=1_000,
        )
    )
    cues = subtitle_cues(document)
    assert cues[0].speech_end_sample == 1_455
    assert cues[0].display_end_sample == 4_800
    assert cues[0].end_milliseconds == 4_799
    assert cues[1].start_milliseconds == 4_800
    assert cues[0].end_milliseconds < cues[1].start_milliseconds
    assert cues[-1].display_end_sample == document.cleaned_total_samples
    assert cues[-1].end_milliseconds == (
        document.cleaned_total_samples * 1_000 + document.sample_rate - 1
    ) // document.sample_rate
    assert cues[-1].speech_end_sample < cues[-1].display_end_sample


def test_sample_rounding_floor_start_ceil_end_without_float_drift(
    alignment_factory: Callable[..., AlignmentResult]
) -> None:
    document = _document(
        alignment_factory(
            "precise",
            word_starts=(1,),
            word_duration=1,
            sample_rate=48_000,
        )
    )
    cue = subtitle_cues(document)[0]
    assert cue.start_milliseconds == 0
    assert cue.speech_end_sample == 2
    assert cue.display_end_sample == document.cleaned_total_samples
    assert cue.end_milliseconds == 1_001


def test_rounding_collision_that_cannot_keep_one_ms_fails(
    alignment_factory: Callable[..., AlignmentResult]
) -> None:
    with pytest.raises(SubtitleValidationError) as captured:
        _document(
            alignment_factory(
                "one. two.",
                word_starts=(0, 1),
                word_duration=1,
                sample_rate=48_000,
            ),
        )
    assert captured.value.code == "INVALID_SRT_CUE_DURATION"


def test_longer_than_one_hour_timecode(
    alignment_factory: Callable[..., AlignmentResult]
) -> None:
    document = _document(
        alignment_factory(
            "long recording",
            word_starts=(3_600_123, 3_601_123),
            word_duration=500,
        )
    )
    assert "01:00:00,123" in render_srt(document).decode("utf-8")


@pytest.mark.parametrize(
    "corruption",
    ["bom", "lf", "index", "timecode", "empty", "text", "overlap"],
)
def test_srt_validator_rejects_corruption(
    alignment_factory: Callable[..., AlignmentResult], corruption: str
) -> None:
    document = _document(
        alignment_factory("one two. three four."),
    )
    payload = render_srt(document)
    text = payload.decode("utf-8")
    if corruption == "bom":
        damaged = codecs.BOM_UTF8 + payload
    elif corruption == "lf":
        damaged = text.replace("\r\n", "\n").encode()
    elif corruption == "index":
        damaged = text.replace("1\r\n", "2\r\n", 1).encode()
    elif corruption == "timecode":
        damaged = text.replace(" --> ", " -> ", 1).encode()
    elif corruption == "empty":
        lines = text.split("\r\n")
        lines[2] = ""
        damaged = "\r\n".join(lines).encode()
    elif corruption == "text":
        damaged = text.replace("one", "ASR", 1).encode()
    else:
        cues = subtitle_cues(document)
        second = f"{cues[1].start_milliseconds // 1000:02d}"
        damaged = text.replace("00:00:02,500", "00:00:00,100").encode()
        if damaged == payload:
            damaged = text.replace("00:00:02,000", "00:00:00,100").encode()
    with pytest.raises(SubtitleExportError):
        validate_srt(damaged, document)


def test_srt_writer_is_atomic_and_deterministic(
    alignment_factory: Callable[..., AlignmentResult], tmp_path: Path
) -> None:
    document = _document(alignment_factory("hello world"))
    destination = tmp_path / "subtitles.srt"
    exporter = SrtExporter()
    exporter.write(document, destination)
    first = destination.read_bytes()
    exporter.write(document, destination)
    assert destination.read_bytes() == first
    assert not list(tmp_path.glob("*.partial.srt"))
