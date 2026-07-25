"""Atomic conversion to the fixed MVP canonical WAV format."""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from larp_audio_mvp.audio.probe import FfprobeAdapter
from larp_audio_mvp.audio.process import ProcessRunner
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import AudioConversionError, ProjectError
from larp_audio_mvp.core.logging import get_logger

_PCM_DURATION_TOLERANCE_SAMPLES = 1
_COMPRESSED_DURATION_TOLERANCE_SAMPLES = 2_400  # 50 ms at 48 kHz.


class CanonicalWavConverter:
    """Always rebuild input as mono 48 kHz PCM s16le WAV.

    Rebuilding canonical inputs as well gives one deterministic FFmpeg path and
    validates headers before atomic publication. No filters, trimming, loudness
    normalization, or silence processing are applied.
    """

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        probe: FfprobeAdapter,
        ffmpeg_path: Path,
        settings: AudioSettings,
    ) -> None:
        self._runner = runner
        self._probe = probe
        self._ffmpeg_path = ffmpeg_path
        self._settings = settings
        self._logger = get_logger("audio.converter")

    def convert(self, source: AudioInfo, destination: Path) -> AudioInfo:
        input_path = source.source_path.expanduser().resolve()
        destination = destination.expanduser().resolve()
        if input_path == destination:
            raise AudioConversionError(
                "canonical destination must differ from the source file",
                code="INPUT_OVERWRITE_FORBIDDEN",
            )
        if destination.exists() and destination.is_dir():
            raise AudioConversionError(
                f"canonical destination is a directory: {destination}",
                code="OUTPUT_IS_DIRECTORY",
            )
        if destination.suffix.lower() != ".wav":
            raise AudioConversionError(
                "canonical destination must use the .wav extension",
                code="INVALID_OUTPUT_EXTENSION",
            )
        if source.stream_index is None:
            raise AudioConversionError(
                "source metadata does not identify an audio stream",
                code="MISSING_STREAM_INDEX",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".partial.wav",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)

        self._logger.info(
            "normalizing audio source_file=%s destination_file=%s",
            input_path.name,
            destination.name,
        )
        try:
            self._runner.run(
                [
                    str(self._ffmpeg_path),
                    "-hide_banner",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(input_path),
                    "-map",
                    f"0:{source.stream_index}",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-ac",
                    str(self._settings.canonical_channels),
                    "-ar",
                    str(self._settings.canonical_sample_rate),
                    "-c:a",
                    self._settings.canonical_codec,
                    "-f",
                    self._settings.canonical_container,
                    str(temporary_path),
                ],
                timeout_seconds=self._settings.subprocess_timeout_seconds,
            )
            canonical = self._probe.probe(temporary_path)
            _validate_canonical(canonical)
            _validate_duration_correspondence(source, canonical)
            os.replace(temporary_path, destination)
            return replace(canonical, source_path=destination)
        except ProjectError:
            raise
        except OSError as exc:
            raise AudioConversionError(
                f"cannot publish canonical WAV: {destination}",
                code="ATOMIC_PUBLISH_FAILED",
            ) from exc
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                self._logger.warning(
                    "could not remove temporary audio file=%s", temporary_path.name
                )


def _validate_canonical(audio: AudioInfo) -> None:
    if not audio.is_canonical:
        raise AudioConversionError(
            "FFmpeg output does not match mono 48 kHz PCM s16le WAV",
            code="CANONICAL_FORMAT_MISMATCH",
        )
    if audio.total_samples is None or audio.total_samples <= 0:
        raise AudioConversionError(
            "canonical WAV has no exact non-zero sample count",
            code="INVALID_CANONICAL_SAMPLE_COUNT",
        )


def _validate_duration_correspondence(
    source: AudioInfo, canonical: AudioInfo
) -> None:
    if source.duration_seconds is None or canonical.total_samples is None:
        return

    expected_samples = source.duration_seconds * canonical.sample_rate
    delta = abs(Fraction(canonical.total_samples) - expected_samples)
    tolerance = (
        _PCM_DURATION_TOLERANCE_SAMPLES
        if source.codec_name and source.codec_name.startswith("pcm_")
        else _COMPRESSED_DURATION_TOLERANCE_SAMPLES
    )
    if delta > tolerance:
        raise AudioConversionError(
            "canonical WAV duration differs from the source by "
            f"{delta.numerator}/{delta.denominator} samples; "
            f"allowed tolerance is {tolerance}",
            code="DURATION_MISMATCH",
        )
