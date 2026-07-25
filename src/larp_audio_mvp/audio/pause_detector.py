"""Read-only FFmpeg pause detector for canonical WAV input."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from larp_audio_mvp.audio.pause_parser import parse_silencedetect_output
from larp_audio_mvp.audio.process import ProcessRunner
from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo, PauseSegment
from larp_audio_mvp.core.errors import PauseDetectionError
from larp_audio_mvp.core.logging import get_logger


class FfmpegPauseDetector:
    """Run ``silencedetect`` into a null sink and return sample intervals."""

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        ffmpeg_path: Path,
        subprocess_timeout_seconds: float,
    ) -> None:
        self._runner = runner
        self._ffmpeg_path = ffmpeg_path
        self._subprocess_timeout_seconds = subprocess_timeout_seconds
        self._logger = get_logger("audio.pause_detector")

    def detect(
        self,
        audio: AudioInfo,
        *,
        settings: PauseSettings,
    ) -> list[PauseSegment]:
        source = _validate_audio(audio)
        threshold = settings.silence_threshold_db
        minimum_duration_ms = settings.minimum_pause_duration_ms
        if threshold is None or minimum_duration_ms is None:
            raise PauseDetectionError(
                "silence_threshold_db and minimum_pause_duration_ms are required",
                code="PAUSE_SETTINGS_INCOMPLETE",
            )

        minimum_pause_samples = _milliseconds_to_samples_ceil(
            minimum_duration_ms, audio.sample_rate
        )
        filter_expression = (
            "silencedetect="
            f"noise={_format_decimal(threshold)}dB:"
            f"d={_format_milliseconds(minimum_duration_ms)}"
        )
        self._logger.info("detecting pauses audio_file=%s", source.name)
        result = self._runner.run(
            [
                str(self._ffmpeg_path),
                "-hide_banner",
                "-nostdin",
                "-nostats",
                "-loglevel",
                "info",
                "-i",
                str(source),
                "-map",
                f"0:{audio.stream_index}",
                "-vn",
                "-sn",
                "-dn",
                "-af",
                filter_expression,
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=self._subprocess_timeout_seconds,
        )
        segments = parse_silencedetect_output(
            result.stderr,
            sample_rate=audio.sample_rate,
            total_samples=audio.total_samples,
            minimum_pause_samples=minimum_pause_samples,
        )
        self._logger.info("pause detection completed count=%d", len(segments))
        return segments


def _validate_audio(audio: AudioInfo) -> Path:
    source = audio.source_path.expanduser().resolve()
    if not source.exists():
        raise PauseDetectionError(
            f"canonical audio does not exist: {source.name}",
            code="INPUT_NOT_FOUND",
        )
    if not source.is_file():
        raise PauseDetectionError(
            f"canonical audio is not a file: {source.name}",
            code="INPUT_NOT_FILE",
        )
    if not audio.is_canonical:
        raise PauseDetectionError(
            "pause detection requires canonical WAV metadata",
            code="NON_CANONICAL_AUDIO",
        )
    if audio.total_samples is None or audio.total_samples <= 0:
        raise PauseDetectionError(
            "pause detection requires an exact positive sample count",
            code="MISSING_TOTAL_SAMPLES",
        )
    if audio.stream_index is None:
        raise PauseDetectionError(
            "pause detection requires an audio stream index",
            code="MISSING_STREAM_INDEX",
        )
    return source


def _milliseconds_to_samples_ceil(milliseconds: int, sample_rate: int) -> int:
    return (milliseconds * sample_rate + 999) // 1_000


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def _format_milliseconds(value: int) -> str:
    return format(Decimal(value) / Decimal(1_000), "f")
