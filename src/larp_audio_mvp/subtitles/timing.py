"""One canonical gapless display timeline for every subtitle consumer."""

from __future__ import annotations

from dataclasses import dataclass

from larp_audio_mvp.core.contracts import SubtitleDocument
from larp_audio_mvp.core.errors import SubtitleTimingError


@dataclass(frozen=True, slots=True)
class GaplessDisplayTiming:
    block_index: int
    speech_start_sample: int
    speech_end_sample: int
    display_start_sample: int
    display_end_sample: int
    srt_start_milliseconds: int
    srt_end_milliseconds: int


@dataclass(frozen=True, slots=True)
class GaplessTimingMetrics:
    internal_gap_count: int
    srt_gap_count: int
    overlap_count: int
    maximum_internal_gap_ms: int
    maximum_srt_gap_ms: int


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def apply_gapless_display_timing(
    document: SubtitleDocument,
) -> tuple[GaplessDisplayTiming, ...]:
    """Derive continuous display/SRT ends while preserving speech intervals."""

    if document.sample_rate <= 0 or document.cleaned_total_samples <= 0:
        raise SubtitleTimingError(
            "subtitle timeline metadata is invalid",
            code="INVALID_GAPLESS_TIMELINE",
        )
    timings: list[GaplessDisplayTiming] = []
    audio_end_ms = _ceil_div(
        document.cleaned_total_samples * 1_000, document.sample_rate
    )
    previous_start = -1
    for offset, block in enumerate(document.blocks):
        start = block.cleaned_start_sample
        if start <= previous_start:
            raise SubtitleTimingError(
                "subtitle starts must be strictly increasing for gapless display",
                code="INVALID_GAPLESS_CUE_ORDER",
            )
        display_end = (
            document.blocks[offset + 1].cleaned_start_sample
            if offset + 1 < len(document.blocks)
            else document.cleaned_total_samples
        )
        if (
            offset + 1 < len(document.blocks)
            and block.cleaned_end_sample
            > document.blocks[offset + 1].cleaned_start_sample
        ):
            raise SubtitleTimingError(
                "subtitle speech intervals overlap",
                code="INVALID_GAPLESS_SPEECH_OVERLAP",
            )
        if not start < display_end <= document.cleaned_total_samples:
            raise SubtitleTimingError(
                "subtitle cue cannot form a positive gapless display interval",
                code="INVALID_GAPLESS_CUE_DURATION",
            )
        start_ms = start * 1_000 // document.sample_rate
        end_ms = (
            document.blocks[offset + 1].cleaned_start_sample
            * 1_000
            // document.sample_rate
            - 1
            if offset + 1 < len(document.blocks)
            else audio_end_ms
        )
        if end_ms <= start_ms:
            raise SubtitleTimingError(
                "subtitle cue cannot form a positive millisecond SRT interval",
                code="INVALID_SRT_CUE_DURATION",
            )
        timings.append(
            GaplessDisplayTiming(
                block_index=block.block_index,
                speech_start_sample=block.cleaned_start_sample,
                speech_end_sample=block.cleaned_end_sample,
                display_start_sample=start,
                display_end_sample=display_end,
                srt_start_milliseconds=start_ms,
                srt_end_milliseconds=end_ms,
            )
        )
        previous_start = start
    validate_gapless_display_timing(tuple(timings), document.sample_rate)
    return tuple(timings)


def validate_gapless_display_timing(
    timings: tuple[GaplessDisplayTiming, ...], sample_rate: int
) -> GaplessTimingMetrics:
    """Strictly prove sample continuity and the intentional 1 ms SRT boundary."""

    internal_gaps: list[int] = []
    srt_gaps: list[int] = []
    overlaps = 0
    for current, following in zip(timings, timings[1:]):
        internal_delta = following.display_start_sample - current.display_end_sample
        if internal_delta < 0:
            overlaps += 1
        elif internal_delta > 0:
            internal_gaps.append(internal_delta)
        srt_delta = following.srt_start_milliseconds - current.srt_end_milliseconds
        if srt_delta < 1:
            overlaps += 1
        elif srt_delta > 1:
            srt_gaps.append(srt_delta - 1)
    metrics = GaplessTimingMetrics(
        internal_gap_count=len(internal_gaps),
        srt_gap_count=len(srt_gaps),
        overlap_count=overlaps,
        maximum_internal_gap_ms=max(
            (gap * 1_000 // sample_rate for gap in internal_gaps), default=0
        ),
        maximum_srt_gap_ms=max(srt_gaps, default=0),
    )
    if any(
        (
            metrics.internal_gap_count,
            metrics.srt_gap_count,
            metrics.overlap_count,
            metrics.maximum_internal_gap_ms,
            metrics.maximum_srt_gap_ms,
        )
    ):
        raise SubtitleTimingError(
            "subtitle display timeline is not strictly gapless",
            code="GAPLESS_TIMELINE_VALIDATION_FAILED",
        )
    return metrics
