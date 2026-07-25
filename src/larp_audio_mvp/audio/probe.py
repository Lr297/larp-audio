"""ffprobe JSON adapter and deterministic audio-stream selection."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from larp_audio_mvp.audio.process import ProcessRunner
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import AudioProbeError
from larp_audio_mvp.core.logging import get_logger


class FfprobeAdapter:
    """Probe local media without modifying it."""

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        ffprobe_path: Path,
        settings: AudioSettings,
    ) -> None:
        self._runner = runner
        self._ffprobe_path = ffprobe_path
        self._settings = settings
        self._logger = get_logger("audio.probe")

    def probe(self, source: Path) -> AudioInfo:
        source = source.expanduser().resolve()
        if not source.exists():
            raise AudioProbeError(
                f"audio input does not exist: {source}", code="INPUT_NOT_FOUND"
            )
        if not source.is_file():
            raise AudioProbeError(
                f"audio input is not a file: {source}", code="INPUT_NOT_FILE"
            )

        self._logger.info("probing audio file=%s", source.name)
        result = self._runner.run(
            [
                str(self._ffprobe_path),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(source),
            ],
            timeout_seconds=self._settings.subprocess_timeout_seconds,
        )
        return self.parse(source, result.stdout)

    def parse(self, source: Path, payload: str) -> AudioInfo:
        """Parse ffprobe JSON for a source that has already been validated."""

        try:
            root = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AudioProbeError(
                "ffprobe returned malformed JSON", code="MALFORMED_FFPROBE_JSON"
            ) from exc
        if not isinstance(root, dict):
            raise AudioProbeError(
                "ffprobe JSON root must be an object",
                code="MALFORMED_FFPROBE_JSON",
            )

        streams = root.get("streams")
        if not isinstance(streams, list):
            raise AudioProbeError(
                "ffprobe JSON does not contain a streams array",
                code="MALFORMED_FFPROBE_JSON",
            )
        stream, audio_stream_count = _select_audio_stream(streams)
        format_info = root.get("format")
        if not isinstance(format_info, dict):
            format_info = {}

        sample_rate = _required_positive_int(stream, "sample_rate")
        channels = _required_positive_int(stream, "channels")
        stream_index = _required_nonnegative_int(stream, "index")
        codec_name = _required_string(stream, "codec_name")
        sample_format = _optional_string(stream, "sample_fmt")
        format_name = _optional_string(format_info, "format_name")
        format_long_name = _optional_string(format_info, "format_long_name")
        bit_depth = _bit_depth(stream)
        duration, duration_source = _duration(stream, format_info)
        total_samples = _exact_total_samples(duration, sample_rate)

        warnings: list[str] = []
        if audio_stream_count > 1:
            warnings.append(
                f"multiple_audio_streams:selected_stream_index={stream_index}"
            )
        if sample_format is None:
            warnings.append("sample_format_unavailable")
        if duration is None:
            warnings.append("duration_unavailable")
        elif total_samples is None:
            warnings.append("exact_total_samples_unavailable")
        if format_name is None:
            warnings.append("container_format_unavailable")

        resolved_source = source.expanduser().resolve()
        try:
            file_size = resolved_source.stat().st_size
            sha256 = _sha256(resolved_source)
        except OSError as exc:
            raise AudioProbeError(
                f"cannot read probed audio file: {resolved_source}",
                code="INPUT_READ_FAILED",
            ) from exc

        is_canonical = _is_canonical(
            format_name=format_name,
            codec_name=codec_name,
            sample_format=sample_format,
            bit_depth=bit_depth,
            sample_rate=sample_rate,
            channels=channels,
            settings=self._settings,
        )
        return AudioInfo(
            source_path=resolved_source,
            format_name=format_name,
            format_long_name=format_long_name,
            codec_name=codec_name,
            sample_rate=sample_rate,
            channels=channels,
            sample_format=sample_format,
            bit_depth=bit_depth,
            duration_seconds=duration,
            duration_source=duration_source,
            total_samples=total_samples,
            file_size_bytes=file_size,
            stream_index=stream_index,
            is_canonical=is_canonical,
            sha256=sha256,
            warnings=tuple(warnings),
        )


def _select_audio_stream(
    streams: Sequence[Any],
) -> tuple[Mapping[str, Any], int]:
    audio_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    if not audio_streams:
        raise AudioProbeError(
            "input does not contain an audio stream", code="NO_AUDIO_STREAM"
        )
    selected = next(
        (stream for stream in audio_streams if _is_default_stream(stream)),
        audio_streams[0],
    )
    return selected, len(audio_streams)


def _is_default_stream(stream: Mapping[str, Any]) -> bool:
    disposition = stream.get("disposition")
    return isinstance(disposition, dict) and disposition.get("default") in (
        1,
        "1",
        True,
    )


def _duration(
    stream: Mapping[str, Any], format_info: Mapping[str, Any]
) -> tuple[Fraction | None, str | None]:
    duration_ts = _optional_int(stream, "duration_ts")
    time_base = _optional_fraction(stream, "time_base")
    if duration_ts is not None and time_base is not None:
        duration = duration_ts * time_base
        if duration < 0:
            raise AudioProbeError(
                "stream duration must be non-negative", code="INVALID_DURATION"
            )
        return duration, "stream_duration_ts"

    stream_duration = _optional_decimal_fraction(stream, "duration")
    if stream_duration is not None:
        return stream_duration, "stream_duration"

    format_duration = _optional_decimal_fraction(format_info, "duration")
    if format_duration is not None:
        return format_duration, "format_duration"
    return None, None


def _exact_total_samples(duration: Fraction | None, sample_rate: int) -> int | None:
    if duration is None:
        return None
    samples = duration * sample_rate
    return samples.numerator if samples.denominator == 1 else None


def _bit_depth(stream: Mapping[str, Any]) -> int | None:
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        value = _optional_int(stream, key)
        if value is not None and value > 0:
            return value
    return None


def _required_positive_int(data: Mapping[str, Any], key: str) -> int:
    value = _optional_int(data, key)
    if value is None:
        raise AudioProbeError(
            f"audio stream is missing {key}", code=f"MISSING_{key.upper()}"
        )
    if value <= 0:
        raise AudioProbeError(
            f"audio stream has invalid {key}: {value}",
            code=f"INVALID_{key.upper()}",
        )
    return value


def _required_nonnegative_int(data: Mapping[str, Any], key: str) -> int:
    value = _optional_int(data, key)
    if value is None or value < 0:
        raise AudioProbeError(
            f"audio stream has invalid {key}: {value}",
            code=f"INVALID_{key.upper()}",
        )
    return value


def _optional_int(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value in (None, "", "N/A"):
        return None
    if isinstance(value, bool):
        raise AudioProbeError(
            f"ffprobe field {key} is not an integer", code="INVALID_NUMERIC_VALUE"
        )
    if isinstance(value, float) and not value.is_integer():
        raise AudioProbeError(
            f"ffprobe field {key} is not an integer", code="INVALID_NUMERIC_VALUE"
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AudioProbeError(
            f"ffprobe field {key} is not an integer", code="INVALID_NUMERIC_VALUE"
        ) from exc


def _optional_fraction(data: Mapping[str, Any], key: str) -> Fraction | None:
    value = data.get(key)
    if value in (None, "", "N/A", "0/0"):
        return None
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise AudioProbeError(
            f"ffprobe field {key} is not a fraction",
            code="INVALID_NUMERIC_VALUE",
        ) from exc
    if result <= 0:
        raise AudioProbeError(
            f"ffprobe field {key} must be positive", code="INVALID_NUMERIC_VALUE"
        )
    return result


def _optional_decimal_fraction(
    data: Mapping[str, Any], key: str
) -> Fraction | None:
    value = data.get(key)
    if value in (None, "", "N/A"):
        return None
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise AudioProbeError(
            f"ffprobe field {key} is not a decimal",
            code="INVALID_NUMERIC_VALUE",
        ) from exc
    if not decimal.is_finite() or decimal < 0:
        raise AudioProbeError(
            f"ffprobe field {key} is not a non-negative finite decimal",
            code="INVALID_DURATION",
        )
    return Fraction(decimal)


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = _optional_string(data, key)
    if value is None:
        raise AudioProbeError(
            f"audio stream is missing {key}", code=f"MISSING_{key.upper()}"
        )
    return value


def _optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value in (None, "", "N/A"):
        return None
    if not isinstance(value, str):
        raise AudioProbeError(
            f"ffprobe field {key} is not a string", code="INVALID_METADATA_VALUE"
        )
    return value


def _is_canonical(
    *,
    format_name: str | None,
    codec_name: str,
    sample_format: str | None,
    bit_depth: int | None,
    sample_rate: int,
    channels: int,
    settings: AudioSettings,
) -> bool:
    formats = {item.strip() for item in format_name.split(",")} if format_name else set()
    return (
        settings.canonical_container in formats
        and codec_name == settings.canonical_codec
        and sample_format == settings.canonical_sample_format
        and (bit_depth in (None, 16))
        and sample_rate == settings.canonical_sample_rate
        and channels == settings.canonical_channels
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
