"""O(log n) subtitle lookup on the canonical cleaned timeline."""

from __future__ import annotations

from bisect import bisect_right

from larp_audio_mvp.core.contracts import SubtitleBlock, SubtitleDocument
from larp_audio_mvp.core.errors import PreviewError
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing

from .contracts import ActiveSubtitleCue


class SubtitleSynchronizer:
    def __init__(self, document: SubtitleDocument) -> None:
        self.document = document
        self._blocks = document.blocks
        try:
            self._timings = apply_gapless_display_timing(document)
        except Exception as exc:
            raise PreviewError(
                "Subtitle display timing is invalid.",
                code="PREVIEW_SUBTITLE_TIMING_INVALID",
            ) from exc
        self._starts = tuple(block.cleaned_start_sample for block in self._blocks)

    def block_at_sample(self, sample: int) -> SubtitleBlock | None:
        if sample < 0 or sample >= self.document.cleaned_total_samples:
            return None
        index = bisect_right(self._starts, sample) - 1
        if index < 0:
            return None
        block = self._blocks[index]
        interval = self._timings[index]
        return (
            block
            if interval.display_start_sample <= sample < interval.display_end_sample
            else None
        )

    def cue_at_milliseconds(self, milliseconds: int) -> ActiveSubtitleCue | None:
        sample = max(0, milliseconds) * self.document.sample_rate // 1000
        block = self.block_at_sample(sample)
        if block is None:
            return None
        index = block.block_index - 1
        return _cue(block, self._timings[index].display_end_sample)

    def milliseconds_for_block(self, block_index: int) -> int:
        if not 1 <= block_index <= len(self._blocks):
            raise PreviewError("Subtitle block does not exist.", code="PREVIEW_CUE_OUT_OF_RANGE")
        return self._blocks[block_index - 1].cleaned_start_sample * 1000 // self.document.sample_rate


def _cue(block: SubtitleBlock, display_end_sample: int) -> ActiveSubtitleCue:
    cps = f"{block.characters_per_second.numerator / block.characters_per_second.denominator:.2f}"
    return ActiveSubtitleCue(
        block.block_index, block.cleaned_start_sample, block.cleaned_end_sample,
        block.display_lines, block.timing_provenance.value, cps, block.word_count,
        block.warnings, block.contains_interpolated_words, block.contains_unresolved_words,
        block.cleaned_start_sample, display_end_sample,
    )
