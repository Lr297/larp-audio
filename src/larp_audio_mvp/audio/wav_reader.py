"""Read exact metadata from an already-canonical PCM WAV header."""

from __future__ import annotations

import hashlib
import wave
from fractions import Fraction
from pathlib import Path

from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import AudioProbeError


def read_canonical_wav(path: Path, settings: AudioSettings) -> AudioInfo:
    """Validate a canonical WAV without creating another ffprobe dependency."""

    source = path.expanduser().resolve()
    if not source.exists():
        raise AudioProbeError(
            f"audio input does not exist: {source.name}", code="INPUT_NOT_FOUND"
        )
    if not source.is_file():
        raise AudioProbeError(
            f"audio input is not a file: {source.name}", code="INPUT_NOT_FILE"
        )
    try:
        with wave.open(str(source), "rb") as input_wav:
            channels = input_wav.getnchannels()
            sample_rate = input_wav.getframerate()
            sample_width = input_wav.getsampwidth()
            total_samples = input_wav.getnframes()
            compression = input_wav.getcomptype()
        with source.open("rb") as input_file:
            sha256 = hashlib.file_digest(input_file, "sha256").hexdigest()
        file_size = source.stat().st_size
    except (OSError, EOFError, wave.Error) as exc:
        raise AudioProbeError(
            "input is not a readable PCM WAV",
            code="INVALID_CANONICAL_WAV",
        ) from exc

    if (
        channels != settings.canonical_channels
        or sample_rate != settings.canonical_sample_rate
        or sample_width != 2
        or compression != "NONE"
    ):
        raise AudioProbeError(
            "input must be mono 48 kHz 16-bit uncompressed PCM WAV",
            code="NON_CANONICAL_AUDIO",
        )
    if total_samples <= 0:
        raise AudioProbeError(
            "canonical WAV must contain at least one sample",
            code="MISSING_TOTAL_SAMPLES",
        )
    return AudioInfo(
        source_path=source,
        format_name="wav",
        format_long_name="WAV / WAVE",
        codec_name=settings.canonical_codec,
        sample_rate=sample_rate,
        channels=channels,
        sample_format=settings.canonical_sample_format,
        duration_seconds=Fraction(total_samples, sample_rate),
        duration_source="wave_header_frames",
        total_samples=total_samples,
        bit_depth=sample_width * 8,
        file_size_bytes=file_size,
        stream_index=0,
        is_canonical=True,
        sha256=sha256,
    )
