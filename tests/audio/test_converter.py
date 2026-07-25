from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Sequence

import pytest

from larp_audio_mvp.audio.converter import CanonicalWavConverter
from larp_audio_mvp.audio.process import CommandResult
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import AudioConversionError, ProcessExecutionError


def _source(path: Path) -> AudioInfo:
    return AudioInfo(
        source_path=path,
        format_name="mp3",
        codec_name="mp3",
        sample_rate=44_100,
        channels=2,
        sample_format="fltp",
        duration_seconds=Fraction(1, 1),
        duration_source="stream_duration",
        total_samples=44_100,
        stream_index=2,
    )


def _canonical(path: Path, *, total_samples: int = 48_000) -> AudioInfo:
    return AudioInfo(
        source_path=path,
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=48_000,
        channels=1,
        sample_format="s16",
        duration_seconds=Fraction(total_samples, 48_000),
        duration_source="stream_duration_ts",
        total_samples=total_samples,
        bit_depth=16,
        stream_index=0,
        is_canonical=True,
    )


class WritingRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def run(
        self, arguments: Sequence[str], *, timeout_seconds: float
    ) -> CommandResult:
        call = list(arguments)
        self.calls.append(call)
        Path(call[-1]).write_bytes(b"canonical")
        if self.fail:
            raise ProcessExecutionError("synthetic conversion failure")
        return CommandResult("", "", 0, 0.01)


class OutputProbe:
    def __init__(self, *, total_samples: int = 48_000) -> None:
        self.total_samples = total_samples
        self.paths: list[Path] = []

    def probe(self, path: Path) -> AudioInfo:
        self.paths.append(path)
        return _canonical(path, total_samples=self.total_samples)


def _converter(
    runner: WritingRunner, probe: OutputProbe
) -> CanonicalWavConverter:
    return CanonicalWavConverter(
        runner=runner,
        probe=probe,  # type: ignore[arg-type]
        ffmpeg_path=Path("/tools/ffmpeg"),
        settings=AudioSettings(),
    )


def test_conversion_is_atomic_and_keeps_source_unchanged(tmp_path: Path) -> None:
    source_path = tmp_path / "вход с пробелами.mp3"
    source_path.write_bytes(b"original")
    destination = tmp_path / "work dir" / "canonical.wav"
    runner = WritingRunner()

    result = _converter(runner, OutputProbe()).convert(
        _source(source_path), destination
    )

    assert source_path.read_bytes() == b"original"
    assert destination.read_bytes() == b"canonical"
    assert result.source_path == destination.resolve()
    assert list(destination.parent.glob("*.partial.wav")) == []
    command = runner.calls[0]
    assert str(source_path.resolve()) in command
    assert command[command.index("-map") + 1] == "0:2"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-c:a") + 1] == "pcm_s16le"
    assert "-af" not in command


def test_partial_output_is_removed_after_process_failure(tmp_path: Path) -> None:
    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"original")
    destination = tmp_path / "canonical.wav"

    with pytest.raises(ProcessExecutionError):
        _converter(WritingRunner(fail=True), OutputProbe()).convert(
            _source(source_path), destination
        )

    assert not destination.exists()
    assert list(tmp_path.glob("*.partial.wav")) == []
    assert source_path.read_bytes() == b"original"


def test_duration_mismatch_prevents_publication(tmp_path: Path) -> None:
    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"original")
    destination = tmp_path / "canonical.wav"

    with pytest.raises(AudioConversionError) as captured:
        _converter(WritingRunner(), OutputProbe(total_samples=40_000)).convert(
            _source(source_path), destination
        )

    assert captured.value.code == "DURATION_MISMATCH"
    assert not destination.exists()
    assert list(tmp_path.glob("*.partial.wav")) == []


def test_input_cannot_be_overwritten(tmp_path: Path) -> None:
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"original")

    with pytest.raises(AudioConversionError) as captured:
        _converter(WritingRunner(), OutputProbe()).convert(
            replace(_source(source_path), format_name="wav"), source_path
        )

    assert captured.value.code == "INPUT_OVERWRITE_FORBIDDEN"
    assert source_path.read_bytes() == b"original"
