from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from larp_audio_mvp.audio.loader import LocalAudioLoader
from larp_audio_mvp.audio.serialization import (
    audio_load_result_to_dict,
    pause_segment_to_dict,
)
from larp_audio_mvp.core.contracts import AudioInfo, AudioLoadResult, PauseSegment


def _info(path: Path, *, canonical: bool) -> AudioInfo:
    return AudioInfo(
        source_path=path,
        format_name="wav" if canonical else "mp3",
        codec_name="pcm_s16le" if canonical else "mp3",
        sample_rate=48_000 if canonical else 44_100,
        channels=1 if canonical else 2,
        sample_format="s16" if canonical else "fltp",
        duration_seconds=Fraction(1, 3),
        duration_source="stream_duration_ts",
        total_samples=16_000 if canonical else 14_700,
        stream_index=0,
        is_canonical=canonical,
        warnings=("test_warning",),
    )


class Probe:
    def probe(self, source: Path) -> AudioInfo:
        return _info(source.resolve(), canonical=False)


class Converter:
    def __init__(self) -> None:
        self.destination: Path | None = None

    def convert(self, source: AudioInfo, destination: Path) -> AudioInfo:
        self.destination = destination
        return _info(destination.resolve(), canonical=True)


def test_loader_orchestrates_probe_then_conversion(tmp_path: Path) -> None:
    converter = Converter()
    loader = LocalAudioLoader(
        probe=Probe(),  # type: ignore[arg-type]
        converter=converter,  # type: ignore[arg-type]
        work_directory=tmp_path / "job",
    )

    result = loader.load(tmp_path / "source.mp3")

    assert result.source_audio.is_canonical is False
    assert result.canonical_audio.is_canonical is True
    assert converter.destination == (tmp_path / "job" / "canonical_audio.wav")


def test_audio_result_serialization_is_json_safe_and_exact(tmp_path: Path) -> None:
    result = AudioLoadResult(
        source_audio=_info(tmp_path / "source ü.mp3", canonical=False),
        canonical_audio=_info(tmp_path / "canonical.wav", canonical=True),
    )

    value = audio_load_result_to_dict(result)
    encoded = json.dumps(value, ensure_ascii=False)

    assert "source ü.mp3" in encoded
    assert value["source_audio"]["duration_seconds"] == {
        "numerator": 1,
        "denominator": 3,
        "decimal": "0.3333333333333333333333333333",
    }
    assert value["canonical_audio"]["warnings"] == ["test_warning"]


def test_pause_segment_serialization_keeps_sample_truth() -> None:
    value = pause_segment_to_dict(
        PauseSegment(start_sample=16_000, end_sample=40_000, sample_rate=48_000)
    )

    assert value["start_sample"] == 16_000
    assert value["end_sample"] == 40_000
    assert value["length_samples"] == 24_000
    assert value["duration_seconds"] == {
        "numerator": 1,
        "denominator": 2,
        "decimal": "0.5",
    }
