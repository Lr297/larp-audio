from __future__ import annotations

import wave
from pathlib import Path

import pytest

from larp_audio_mvp.app.detect_pauses import _read_canonical_wav, main
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.errors import PauseDetectionError


def _write_wav(path: Path, *, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\0\0" * channels * 100)


def test_cli_canonical_wav_reader_uses_exact_header_samples(
    tmp_path: Path,
) -> None:
    source = tmp_path / "canonical ü.wav"
    _write_wav(source)

    info = _read_canonical_wav(source, AudioSettings())

    assert info.total_samples == 100
    assert info.sample_rate == 48_000
    assert info.duration_seconds is not None
    assert info.duration_seconds.numerator == 1
    assert info.duration_seconds.denominator == 480
    assert info.is_canonical is True


def test_cli_reader_rejects_noncanonical_wav(tmp_path: Path) -> None:
    source = tmp_path / "stereo.wav"
    _write_wav(source, channels=2)

    with pytest.raises(PauseDetectionError) as captured:
        _read_canonical_wav(source, AudioSettings())

    assert captured.value.code == "NON_CANONICAL_AUDIO"


def test_cli_reports_missing_explicit_ffmpeg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "audio.wav"
    _write_wav(source)

    exit_code = main(
        [
            str(source),
            "--silence-threshold-db",
            "-40",
            "--minimum-pause-duration-ms",
            "300",
            "--ffmpeg",
            str(tmp_path / "missing ffmpeg"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error [TOOL_NOT_FOUND]" in captured.err
