"""Pure parser for FFmpeg ``silencedetect`` diagnostic output."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from larp_audio_mvp.core.contracts import PauseSegment
from larp_audio_mvp.core.errors import PauseDetectionError

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_START_PATTERN = re.compile(rf"silence_start\s*:\s*(?P<value>{_NUMBER})")
_END_PATTERN = re.compile(rf"silence_end\s*:\s*(?P<value>{_NUMBER})")
_BOUNDARY_TOLERANCE_SAMPLES = 1


def parse_silencedetect_output(
    stderr: str,
    *,
    sample_rate: int,
    total_samples: int,
    minimum_pause_samples: int = 1,
) -> list[PauseSegment]:
    """Return sorted, non-overlapping sample intervals from FFmpeg stderr.

    Start times are rounded toward the interior with ``ceil`` and end times
    with ``floor``. This prevents decimal log precision from expanding a
    silence interval into neighboring speech.
    """

    _validate_bounds(sample_rate, total_samples, minimum_pause_samples)
    active_start: Decimal | None = None
    raw_segments: list[PauseSegment] = []

    for line in stderr.splitlines():
        start_match = _START_PATTERN.search(line)
        end_match = _END_PATTERN.search(line)
        if "silence_start" in line and start_match is None:
            raise PauseDetectionError(
                "truncated or malformed silence_start event",
                code="MALFORMED_SILENCE_EVENT",
            )
        if "silence_end" in line and end_match is None:
            raise PauseDetectionError(
                "truncated or malformed silence_end event",
                code="MALFORMED_SILENCE_EVENT",
            )

        if start_match is not None:
            if active_start is not None:
                raise PauseDetectionError(
                    "silence_start appeared before the prior interval ended",
                    code="OVERLAPPING_SILENCE_EVENTS",
                )
            active_start = _parse_seconds(start_match.group("value"))

        if end_match is not None:
            if active_start is None:
                raise PauseDetectionError(
                    "silence_end appeared without silence_start",
                    code="UNPAIRED_SILENCE_END",
                )
            end_seconds = _parse_seconds(end_match.group("value"))
            start_sample = _ceil_fraction(Fraction(active_start) * sample_rate)
            end_sample = _floor_fraction(Fraction(end_seconds) * sample_rate)
            raw_segments.append(
                _bounded_segment(
                    start_sample=start_sample,
                    end_sample=end_sample,
                    sample_rate=sample_rate,
                    total_samples=total_samples,
                )
            )
            active_start = None

    if active_start is not None:
        raise PauseDetectionError(
            "silencedetect output ended before silence_end",
            code="TRUNCATED_SILENCE_EVENT",
        )

    return _normalize_segments(raw_segments, minimum_pause_samples)


def _parse_seconds(value: str) -> Decimal:
    try:
        seconds = Decimal(value)
    except InvalidOperation as exc:
        raise PauseDetectionError(
            "silencedetect timestamp is not a decimal",
            code="INVALID_SILENCE_TIMESTAMP",
        ) from exc
    if not seconds.is_finite() or seconds < 0:
        raise PauseDetectionError(
            "silencedetect timestamp must be non-negative and finite",
            code="INVALID_SILENCE_TIMESTAMP",
        )
    return seconds


def _bounded_segment(
    *,
    start_sample: int,
    end_sample: int,
    sample_rate: int,
    total_samples: int,
) -> PauseSegment:
    if start_sample > total_samples:
        raise PauseDetectionError(
            "silence start exceeds the audio sample count",
            code="PAUSE_OUT_OF_BOUNDS",
        )
    if end_sample > total_samples:
        if end_sample - total_samples > _BOUNDARY_TOLERANCE_SAMPLES:
            raise PauseDetectionError(
                "silence end exceeds the audio sample count",
                code="PAUSE_OUT_OF_BOUNDS",
            )
        end_sample = total_samples
    if end_sample <= start_sample:
        raise PauseDetectionError(
            "silencedetect produced an empty or negative interval",
            code="INVALID_PAUSE_INTERVAL",
        )
    return PauseSegment(
        start_sample=start_sample,
        end_sample=end_sample,
        sample_rate=sample_rate,
    )


def _normalize_segments(
    segments: list[PauseSegment], minimum_pause_samples: int
) -> list[PauseSegment]:
    merged: list[PauseSegment] = []
    for segment in sorted(
        segments, key=lambda item: (item.start_sample, item.end_sample)
    ):
        if not merged or segment.start_sample > merged[-1].end_sample:
            merged.append(segment)
            continue
        previous = merged[-1]
        merged[-1] = PauseSegment(
            start_sample=previous.start_sample,
            end_sample=max(previous.end_sample, segment.end_sample),
            sample_rate=previous.sample_rate,
        )
    return [
        segment
        for segment in merged
        if segment.length_samples >= minimum_pause_samples
    ]


def _validate_bounds(
    sample_rate: int, total_samples: int, minimum_pause_samples: int
) -> None:
    for name, value in (
        ("sample_rate", sample_rate),
        ("total_samples", total_samples),
        ("minimum_pause_samples", minimum_pause_samples),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if total_samples <= 0:
        raise ValueError("total_samples must be positive")
    if minimum_pause_samples <= 0:
        raise ValueError("minimum_pause_samples must be positive")


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _floor_fraction(value: Fraction) -> int:
    return value.numerator // value.denominator
