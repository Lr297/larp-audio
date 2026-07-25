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

from larp_audio_mvp.app.remove_pauses import main as remove_pauses_main
from larp_audio_mvp.audio import (
    EditMapBuilder,
    FfmpegWavRenderer,
    FfprobeAdapter,
    PauseRemovalService,
    PauseShorteningPolicy,
    SubprocessRunner,
)
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.config import AudioSettings, PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo, PauseSegment
from larp_audio_mvp.core.timeline import TimelineMapper

pytestmark = pytest.mark.integration

_RATE = 48_000


@pytest.fixture(scope="module")
def ffmpeg_tool() -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("pause removal integration tests require ffmpeg on PATH")
    return Path(ffmpeg).resolve()


@pytest.fixture(scope="module")
def media_tools(ffmpeg_tool: Path) -> tuple[Path, Path]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("full pause removal CLI requires ffprobe on PATH")
    return ffmpeg_tool, Path(ffprobe).resolve()


def _write_synthetic_wav(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    values: list[int] = []
    for seconds, tone in (
        (0.4, True),
        (0.6, False),
        (0.4, True),
        (0.8, False),
        (0.4, True),
    ):
        count = round(seconds * _RATE)
        offset = len(values)
        for index in range(count):
            values.append(
                int(
                    12_000
                    * math.sin(2 * math.pi * 440 * (offset + index) / _RATE)
                )
                if tone
                else 0
            )
    frames = b"".join(struct.pack("<h", value) for value in values)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(_RATE)
        output.writeframes(frames)
    return len(values)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audio(path: Path, total_samples: int) -> AudioInfo:
    return AudioInfo(
        source_path=path.resolve(),
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=_RATE,
        channels=1,
        sample_format="s16",
        duration_seconds=Fraction(total_samples, _RATE),
        duration_source="synthetic_fixture",
        total_samples=total_samples,
        bit_depth=16,
        stream_index=0,
        is_canonical=True,
        sha256=_sha256(path),
    )


class WaveProbe:
    def probe(self, path: Path) -> AudioInfo:
        with wave.open(str(path), "rb") as input_wav:
            channels = input_wav.getnchannels()
            sample_rate = input_wav.getframerate()
            total_samples = input_wav.getnframes()
            sample_width = input_wav.getsampwidth()
        return AudioInfo(
            source_path=path.resolve(),
            format_name="wav",
            codec_name="pcm_s16le",
            sample_rate=sample_rate,
            channels=channels,
            sample_format="s16",
            duration_seconds=Fraction(total_samples, sample_rate),
            duration_source="wave_header_frames",
            total_samples=total_samples,
            bit_depth=sample_width * 8,
            stream_index=0,
            is_canonical=(
                channels == 1 and sample_rate == _RATE and sample_width == 2
            ),
            sha256=_sha256(path),
        )


def _pause_settings() -> PauseSettings:
    return PauseSettings(
        silence_threshold_db=Decimal("-50"),
        minimum_pause_duration_ms=300,
        shortening_policy_version="integration-v1",
        minimum_pause_to_shorten_ms=500,
        target_remaining_pause_ms=200,
        maximum_removed_per_pause_ms=1_000,
    )


def test_real_ffmpeg_renders_edit_map_exactly_and_preserves_source(
    tmp_path: Path, ffmpeg_tool: Path
) -> None:
    source = tmp_path / "исходный файл ü.wav"
    total_samples = _write_synthetic_wav(source)
    before_hash = _sha256(source)
    audio = _audio(source, total_samples)
    policy = PauseShorteningPolicy(_pause_settings())
    renderer = FfmpegWavRenderer(
        runner=SubprocessRunner(),
        probe=WaveProbe(),  # type: ignore[arg-type]
        ffmpeg_path=ffmpeg_tool,
        settings=AudioSettings(subprocess_timeout_seconds=30.0),
    )
    service = PauseRemovalService(
        policy=policy,
        builder=EditMapBuilder(),
        renderer=renderer,
    )
    pauses = [
        PauseSegment(19_200, 48_000, _RATE),
        PauseSegment(67_200, 105_600, _RATE),
    ]
    destination = tmp_path / "результат с пробелами" / "cleaned_audio.wav"

    result = service.remove(audio, pauses, destination=destination)
    edit_map_path = destination.parent / "edit_map.json"
    write_edit_map_atomic(result.edit_map, edit_map_path)

    assert _sha256(source) == before_hash
    assert result.edit_map.source_total_samples == 124_800
    assert result.edit_map.output_total_samples == 76_800
    assert result.edit_map.removed_samples == 48_000
    assert result.cleaned_audio is not None
    assert result.cleaned_audio.total_samples == 76_800
    assert result.cleaned_audio.sample_rate == _RATE
    assert result.cleaned_audio.channels == 1
    assert result.cleaned_audio.codec_name == "pcm_s16le"
    assert result.cleaned_audio.sha256 == _sha256(destination)
    assert json.loads(edit_map_path.read_text(encoding="utf-8"))["audio"][
        "target_total_samples"
    ] == 76_800
    mapper = TimelineMapper(result.edit_map)
    assert mapper.source_to_target(50_000) == 30_800
    assert mapper.target_to_source(24_000) == 43_200
    assert mapper.target_to_source(52_800) == 100_800
    assert list(destination.parent.glob("*.partial.*")) == []


def test_full_remove_pauses_cli_with_ffprobe(
    tmp_path: Path,
    media_tools: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    ffmpeg, ffprobe = media_tools
    source = tmp_path / "CLI вход ü.wav"
    total_samples = _write_synthetic_wav(source)
    before_hash = _sha256(source)
    output = tmp_path / "CLI output"

    exit_code = remove_pauses_main(
        [
            str(source),
            "--work-directory",
            str(output),
            "--silence-threshold-db",
            "-50",
            "--minimum-pause-duration-ms",
            "300",
            "--policy-version",
            "cli-v1",
            "--minimum-pause-to-shorten-ms",
            "500",
            "--target-remaining-pause-ms",
            "200",
            "--maximum-removed-per-pause-ms",
            "1000",
            "--ffmpeg",
            str(ffmpeg),
            "--ffprobe",
            str(ffprobe),
            "--timeout",
            "30",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["source_total_samples"] == total_samples
    assert payload["target_total_samples"] < total_samples
    assert payload["removed_samples"] == (
        payload["source_total_samples"] - payload["target_total_samples"]
    )
    assert (output / "cleaned_audio.wav").exists()
    assert (output / "edit_map.json").exists()
    assert _sha256(source) == before_hash
