from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import wave
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from larp_audio_mvp.app.detect_pauses import main as detect_pauses_main
from larp_audio_mvp.audio import FfmpegPauseDetector, SubprocessRunner
from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo, PauseSegment

pytestmark = pytest.mark.integration

_SAMPLE_RATE = 48_000
_EXPECTED = ((19_200, 48_000), (67_200, 105_600))
_TOLERANCE_SAMPLES = 256


@pytest.fixture(scope="module")
def ffmpeg_tool() -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("pause detection integration tests require ffmpeg on PATH")
    return Path(ffmpeg).resolve()


def _write_synthetic_wav(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples: list[int] = []
    for duration_seconds, tone in (
        (0.4, True),
        (0.6, False),
        (0.4, True),
        (0.8, False),
        (0.4, True),
    ):
        count = round(duration_seconds * _SAMPLE_RATE)
        offset = len(samples)
        for index in range(count):
            value = (
                int(
                    12_000
                    * math.sin(
                        2 * math.pi * 440 * (offset + index) / _SAMPLE_RATE
                    )
                )
                if tone
                else 0
            )
            samples.append(value)
    frames = b"".join(struct.pack("<h", value) for value in samples)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(_SAMPLE_RATE)
        output.writeframes(frames)
    return len(samples)


def _audio(path: Path, total_samples: int) -> AudioInfo:
    return AudioInfo(
        source_path=path,
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=_SAMPLE_RATE,
        channels=1,
        sample_format="s16",
        duration_seconds=Fraction(total_samples, _SAMPLE_RATE),
        duration_source="synthetic_fixture",
        total_samples=total_samples,
        bit_depth=16,
        stream_index=0,
        is_canonical=True,
    )


def _settings() -> PauseSettings:
    return PauseSettings(
        silence_threshold_db=Decimal("-50"),
        minimum_pause_duration_ms=300,
    )


def _assert_expected(segments: list[PauseSegment]) -> None:
    assert len(segments) == 2
    for segment, (expected_start, expected_end) in zip(segments, _EXPECTED):
        assert abs(segment.start_sample - expected_start) <= _TOLERANCE_SAMPLES
        assert abs(segment.end_sample - expected_end) <= _TOLERANCE_SAMPLES


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_ffmpeg_finds_synthetic_pauses_without_writing_audio(
    tmp_path: Path, ffmpeg_tool: Path
) -> None:
    source = tmp_path / "паузы в пути ü.wav"
    total_samples = _write_synthetic_wav(source)
    before_hash = _sha256(source)
    detector = FfmpegPauseDetector(
        runner=SubprocessRunner(),
        ffmpeg_path=ffmpeg_tool,
        subprocess_timeout_seconds=30.0,
    )

    segments = detector.detect(_audio(source, total_samples), settings=_settings())

    _assert_expected(segments)
    assert _sha256(source) == before_hash
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]


def test_real_cli_outputs_json_and_preserves_source(
    tmp_path: Path,
    ffmpeg_tool: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "CLI папка с пробелами" / "вход ü.wav"
    _write_synthetic_wav(source)
    before_hash = _sha256(source)

    exit_code = detect_pauses_main(
        [
            str(source),
            "--silence-threshold-db",
            "-50",
            "--minimum-pause-duration-ms",
            "300",
            "--ffmpeg",
            str(ffmpeg_tool),
            "--timeout",
            "30",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["sample_rate"] == _SAMPLE_RATE
    assert payload["total_samples"] == 124_800
    assert len(payload["pauses"]) == 2
    assert _sha256(source) == before_hash
