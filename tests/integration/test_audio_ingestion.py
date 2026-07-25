from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import wave
from fractions import Fraction
from pathlib import Path

import pytest

from larp_audio_mvp.app.audio_inspect import main as audio_inspect_main
from larp_audio_mvp.audio import (
    CanonicalWavConverter,
    FfprobeAdapter,
    LocalAudioLoader,
    SubprocessRunner,
)
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import AudioProbeError

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def ffmpeg_tool() -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("integration tests require ffmpeg on PATH")
    return Path(ffmpeg).resolve()


@pytest.fixture(scope="module")
def media_tools(ffmpeg_tool: Path) -> tuple[Path, Path]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("integration tests require both ffmpeg and ffprobe on PATH")
    return ffmpeg_tool, Path(ffprobe).resolve()


def _write_stereo_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44_100
    frame_count = sample_rate // 4
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        for index in range(frame_count):
            sample = int(
                8_000 * math.sin(2 * math.pi * 440 * index / sample_rate)
            )
            output.writeframesraw(struct.pack("<hh", sample, -sample))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _loader(
    work_directory: Path, ffmpeg: Path, ffprobe: Path
) -> tuple[FfprobeAdapter, LocalAudioLoader]:
    settings = AudioSettings(subprocess_timeout_seconds=30.0)
    runner = SubprocessRunner()
    probe = FfprobeAdapter(
        runner=runner,
        ffprobe_path=ffprobe,
        settings=settings,
    )
    converter = CanonicalWavConverter(
        runner=runner,
        probe=probe,
        ffmpeg_path=ffmpeg,
        settings=settings,
    )
    loader = LocalAudioLoader(
        probe=probe,
        converter=converter,
        work_directory=work_directory,
    )
    return probe, loader


def test_real_probe_and_normalization_preserve_source(
    tmp_path: Path, media_tools: tuple[Path, Path]
) -> None:
    ffmpeg, ffprobe = media_tools
    source = tmp_path / "папка с пробелами" / "синтетика ü.wav"
    _write_stereo_wav(source)
    before_hash = _sha256(source)
    probe, loader = _loader(tmp_path / "рабочая папка", ffmpeg, ffprobe)

    probed = probe.probe(source)
    result = loader.load(source)

    assert probed.sample_rate == 44_100
    assert probed.channels == 2
    assert result.source_audio.sha256 == before_hash
    assert _sha256(source) == before_hash
    canonical = result.canonical_audio
    assert canonical.source_path.exists()
    assert canonical.format_name is not None and "wav" in canonical.format_name
    assert canonical.codec_name == "pcm_s16le"
    assert canonical.sample_format == "s16"
    assert canonical.sample_rate == 48_000
    assert canonical.channels == 1
    assert canonical.total_samples is not None and canonical.total_samples > 0
    assert canonical.is_canonical is True


def test_real_cli_returns_json(
    tmp_path: Path,
    media_tools: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    ffmpeg, ffprobe = media_tools
    source = tmp_path / "CLI вход ü.wav"
    _write_stereo_wav(source)
    before_hash = _sha256(source)

    exit_code = audio_inspect_main(
        [
            str(source),
            "--work-directory",
            str(tmp_path / "CLI work"),
            "--ffmpeg",
            str(ffmpeg),
            "--ffprobe",
            str(ffprobe),
            "--timeout",
            "30",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["canonical_audio"]["sample_rate"] == 48_000
    assert payload["canonical_audio"]["channels"] == 1
    assert _sha256(source) == before_hash


class _RejectingProbe:
    def probe(self, path: Path) -> AudioInfo:
        raise AudioProbeError("synthetic post-conversion rejection")


def test_real_ffmpeg_partial_is_removed_after_post_probe_failure(
    tmp_path: Path, ffmpeg_tool: Path
) -> None:
    source = tmp_path / "atomic source ü.wav"
    _write_stereo_wav(source)
    before_hash = _sha256(source)
    source_info = AudioInfo(
        source_path=source,
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=44_100,
        channels=2,
        sample_format="s16",
        duration_seconds=Fraction(1, 4),
        duration_source="wave_fixture",
        total_samples=11_025,
        stream_index=0,
    )
    destination = tmp_path / "atomic work" / "canonical.wav"
    converter = CanonicalWavConverter(
        runner=SubprocessRunner(),
        probe=_RejectingProbe(),  # type: ignore[arg-type]
        ffmpeg_path=ffmpeg_tool,
        settings=AudioSettings(subprocess_timeout_seconds=30.0),
    )

    with pytest.raises(AudioProbeError):
        converter.convert(source_info, destination)

    assert _sha256(source) == before_hash
    assert not destination.exists()
    assert list(destination.parent.glob("*.partial.wav")) == []
