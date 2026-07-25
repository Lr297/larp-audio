from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Sequence

import pytest

from larp_audio_mvp.audio.pause_detector import FfmpegPauseDetector
from larp_audio_mvp.audio.process import CommandResult
from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import (
    PauseDetectionError,
    ProcessExecutionError,
)


class Runner:
    def __init__(self, stderr: str) -> None:
        self.stderr = stderr
        self.calls: list[tuple[list[str], float]] = []

    def run(
        self, arguments: Sequence[str], *, timeout_seconds: float
    ) -> CommandResult:
        self.calls.append((list(arguments), timeout_seconds))
        return CommandResult("", self.stderr, 0, 0.01)


class FailingRunner:
    def run(
        self, arguments: Sequence[str], *, timeout_seconds: float
    ) -> CommandResult:
        raise ProcessExecutionError("synthetic FFmpeg error")


def _audio(path: Path, *, canonical: bool = True) -> AudioInfo:
    return AudioInfo(
        source_path=path,
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=48_000,
        channels=1,
        sample_format="s16",
        duration_seconds=Fraction(2, 1),
        duration_source="test",
        total_samples=96_000,
        stream_index=0,
        is_canonical=canonical,
    )


def _settings() -> PauseSettings:
    return PauseSettings(
        silence_threshold_db=Decimal("-42.5"),
        minimum_pause_duration_ms=500,
    )


def test_detector_runs_read_only_ffmpeg_and_parses_result(tmp_path: Path) -> None:
    source = tmp_path / "канонический файл.wav"
    source.write_bytes(b"unchanged")
    runner = Runner("silence_start: 0.5\nsilence_end: 1.25")
    detector = FfmpegPauseDetector(
        runner=runner,
        ffmpeg_path=Path("/tools/ffmpeg"),
        subprocess_timeout_seconds=12.0,
    )

    segments = detector.detect(_audio(source), settings=_settings())

    assert source.read_bytes() == b"unchanged"
    assert [(item.start_sample, item.end_sample) for item in segments] == [
        (24_000, 60_000)
    ]
    command, timeout = runner.calls[0]
    assert command[command.index("-i") + 1] == str(source.resolve())
    assert command[command.index("-map") + 1] == "0:0"
    assert command[command.index("-af") + 1] == (
        "silencedetect=noise=-42.5dB:d=0.5"
    )
    assert command[-3:] == ["-f", "null", "-"]
    assert "-y" not in command
    assert timeout == 12.0


def test_detector_requires_explicit_settings(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")
    detector = FfmpegPauseDetector(
        runner=Runner(""),
        ffmpeg_path=Path("/tools/ffmpeg"),
        subprocess_timeout_seconds=12.0,
    )

    with pytest.raises(PauseDetectionError) as captured:
        detector.detect(_audio(source), settings=PauseSettings())

    assert captured.value.code == "PAUSE_SETTINGS_INCOMPLETE"


def test_detector_rejects_noncanonical_input_before_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")
    runner = Runner("")
    detector = FfmpegPauseDetector(
        runner=runner,
        ffmpeg_path=Path("/tools/ffmpeg"),
        subprocess_timeout_seconds=12.0,
    )

    with pytest.raises(PauseDetectionError) as captured:
        detector.detect(_audio(source, canonical=False), settings=_settings())

    assert captured.value.code == "NON_CANONICAL_AUDIO"
    assert runner.calls == []


def test_ffmpeg_error_is_propagated(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")
    detector = FfmpegPauseDetector(
        runner=FailingRunner(),
        ffmpeg_path=Path("/tools/ffmpeg"),
        subprocess_timeout_seconds=12.0,
    )

    with pytest.raises(ProcessExecutionError):
        detector.detect(_audio(source), settings=_settings())
