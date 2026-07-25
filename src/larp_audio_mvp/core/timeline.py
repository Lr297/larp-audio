"""O(log n) sample mapping over a validated immutable edit map."""

from __future__ import annotations

from bisect import bisect_right

from larp_audio_mvp.core.contracts import EditKind, EditMap, EditSpan
from larp_audio_mvp.core.errors import TimelineMappingError


class TimelineMapper:
    """Map source/target sample indices using binary-searched span starts.

    A removed source sample collapses to its cut anchor. A target sample maps
    to exactly one kept source sample. Endpoints map total-to-total.
    """

    def __init__(self, edit_map: EditMap) -> None:
        self._edit_map = edit_map
        self._source_spans = edit_map.spans
        self._source_starts = tuple(span.source_start for span in edit_map.spans)
        self._target_spans = tuple(
            span for span in edit_map.spans if span.kind is EditKind.KEEP
        )
        self._target_starts = tuple(span.target_start for span in self._target_spans)

    def source_to_target(self, source_sample: int) -> int:
        _validate_sample(
            source_sample,
            maximum=self._edit_map.source_total_samples,
            timeline="source",
        )
        if source_sample == self._edit_map.source_total_samples:
            return self._edit_map.output_total_samples
        span = self._find_source_span(source_sample)
        if span.kind is EditKind.REMOVE:
            return span.target_start
        return span.target_start + (source_sample - span.source_start)

    def target_to_source(self, target_sample: int) -> int:
        _validate_sample(
            target_sample,
            maximum=self._edit_map.output_total_samples,
            timeline="target",
        )
        if target_sample == self._edit_map.output_total_samples:
            return self._edit_map.source_total_samples
        index = bisect_right(self._target_starts, target_sample) - 1
        if index < 0:
            raise TimelineMappingError(
                "target sample is not covered by the edit map",
                code="TARGET_SAMPLE_UNMAPPED",
            )
        span = self._target_spans[index]
        if target_sample >= span.target_end:
            raise TimelineMappingError(
                "target sample is not covered by the edit map",
                code="TARGET_SAMPLE_UNMAPPED",
            )
        return span.source_start + (target_sample - span.target_start)

    def _find_source_span(self, source_sample: int) -> EditSpan:
        index = bisect_right(self._source_starts, source_sample) - 1
        if index < 0:
            raise TimelineMappingError(
                "source sample is not covered by the edit map",
                code="SOURCE_SAMPLE_UNMAPPED",
            )
        span = self._source_spans[index]
        if source_sample >= span.source_end:
            raise TimelineMappingError(
                "source sample is not covered by the edit map",
                code="SOURCE_SAMPLE_UNMAPPED",
            )
        return span


def _validate_sample(value: int, *, maximum: int, timeline: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimelineMappingError(
            f"{timeline} sample must be an integer", code="INVALID_SAMPLE_INDEX"
        )
    if value < 0 or value > maximum:
        raise TimelineMappingError(
            f"{timeline} sample is outside [0, {maximum}]",
            code="SAMPLE_OUT_OF_BOUNDS",
        )
