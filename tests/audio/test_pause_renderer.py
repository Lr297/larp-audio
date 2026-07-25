from __future__ import annotations

import hashlib
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Sequence

import pytest

from larp_audio_mvp.audio.edit_map_builder import EditMapBuilder
from larp_audio_mvp.audio.pause_policy import PauseShorteningPolicy
from larp_audio_mvp.audio.pause_removal import PauseRemovalService
from larp_audio_mvp.audio.pause_renderer import FfmpegWavRenderer
from larp_audio_mvp.audio.process import CommandResult
from larp_audio_mvp.config import AudioSettings, PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo, EditMap, PauseSegment
from larp_audio_mvp.core.errors import AudioRenderError


class WritingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self, arguments: Sequence[str], *, timeout_seconds: float
    ) -> CommandResult:
        command = list(arguments)
        self.calls.append(command)
        Path(command[-1]).write_bytes(b"rendered")
        return CommandResult("", "", 0, 0.01)


class OutputProbe:
    def __init__(self, *, total_samples: int, mismatch: bool = False) -> None:
        self.total_samples = total_samples
        self.mismatch = mismatch

    def probe(self, path: Path) -> AudioInfo:
        samples = self.total_samples + (1 if self.mismatch else 0)
        return AudioInfo(
            source_path=path,
            format_name="wav",
            codec_name="pcm_s16le",
            sample_rate=48_000,
            channels=1,
            sample_format="s16",
            duration_seconds=Fraction(samples, 48_000),
            duration_source="test",
            total_samples=samples,
            stream_index=0,
            is_canonical=True,
            sha256="target-hash",
        )


def _settings() -> PauseSettings:
    return PauseSettings(
        silence_threshold_db=Decimal("-50"),
        minimum_pause_duration_ms=300,
        shortening_policy_version="test-v1",
        minimum_pause_to_shorten_ms=1_000,
        target_remaining_pause_ms=500,
        maximum_removed_per_pause_ms=2_000,
    )


def _audio(path: Path) -> AudioInfo:
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return AudioInfo(
        source_path=path,
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=48_000,
        channels=1,
        sample_format="s16",
        duration_seconds=Fraction(4, 1),
        duration_source="test",
        total_samples=192_000,
        stream_index=0,
        is_canonical=True,
        sha256=source_hash,
    )


def _edit_map(audio: AudioInfo) -> tuple[PauseShorteningPolicy, EditMap]:
    policy = PauseShorteningPolicy(_settings())
    decisions = policy.decide(
        [PauseSegment(48_000, 144_000, 48_000)],
        total_samples=192_000,
        sample_rate=48_000,
    )
    return policy, EditMapBuilder().build(audio, decisions, policy=policy)


def test_renderer_uses_only_kept_edit_map_spans_and_is_atomic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source ü.wav"
    source.write_bytes(b"source")
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    audio = _audio(source)
    _, edit_map = _edit_map(audio)
    runner = WritingRunner()
    destination = tmp_path / "work dir" / "cleaned_audio.wav"
    renderer = FfmpegWavRenderer(
        runner=runner,
        probe=OutputProbe(total_samples=edit_map.output_total_samples),  # type: ignore[arg-type]
        ffmpeg_path=Path("/tools/ffmpeg"),
        settings=AudioSettings(),
    )

    output = renderer.render(audio, edit_map, destination)

    assert output.source_path == destination.resolve()
    assert output.total_samples == 120_000
    assert destination.read_bytes() == b"rendered"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash
    assert list(destination.parent.glob("*.partial.wav")) == []
    command = runner.calls[0]
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:0]asplit=2" in graph
    assert "atrim=start_sample=0:end_sample=60000" in graph
    assert "atrim=start_sample=132000:end_sample=192000" in graph
    assert "concat=n=2:v=0:a=1[outa]" in graph


def test_renderer_does_not_publish_sample_count_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    audio = _audio(source)
    _, edit_map = _edit_map(audio)
    destination = tmp_path / "cleaned_audio.wav"
    renderer = FfmpegWavRenderer(
        runner=WritingRunner(),
        probe=OutputProbe(
            total_samples=edit_map.output_total_samples,
            mismatch=True,
        ),  # type: ignore[arg-type]
        ffmpeg_path=Path("/tools/ffmpeg"),
        settings=AudioSettings(),
    )

    with pytest.raises(AudioRenderError) as captured:
        renderer.render(audio, edit_map, destination)

    assert captured.value.code == "OUTPUT_SAMPLE_COUNT_MISMATCH"
    assert not destination.exists()
    assert list(tmp_path.glob("*.partial.wav")) == []


class ServiceRenderer:
    def render(
        self, audio: AudioInfo, edit_map: EditMap, destination: Path
    ) -> AudioInfo:
        return AudioInfo(
            source_path=destination.resolve(),
            format_name="wav",
            codec_name="pcm_s16le",
            sample_rate=audio.sample_rate,
            channels=audio.channels,
            sample_format=audio.sample_format,
            total_samples=edit_map.output_total_samples,
            stream_index=0,
            is_canonical=True,
            sha256="service-target-hash",
        )


def test_service_returns_completed_edit_map_with_output_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    audio = _audio(source)
    policy = PauseShorteningPolicy(_settings())
    service = PauseRemovalService(
        policy=policy,
        builder=EditMapBuilder(),
        renderer=ServiceRenderer(),  # type: ignore[arg-type]
    )

    result = service.remove(
        audio,
        [PauseSegment(48_000, 144_000, 48_000)],
        destination=tmp_path / "cleaned.wav",
    )

    assert result.edit_map.output_sha256 == "service-target-hash"
    assert result.edit_map.removed_samples == 72_000
    assert result.cleaned_audio is not None
    assert result.cleaned_audio.total_samples == 120_000
