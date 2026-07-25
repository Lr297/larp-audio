"""Deterministic scored segmentation of exact script spans into subtitle blocks."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from time import perf_counter_ns

from larp_audio_mvp.alignment import validate_alignment_result
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import (
    AlignedScriptWord,
    AlignmentResult,
    ScriptToken,
    SubtitleBlock,
    SubtitleDocument,
    SubtitleTimingProvenance,
    TimingStatus,
)
from larp_audio_mvp.core.errors import (
    SubtitleChunkingError,
    SubtitleComplexityLimitError,
    SubtitleCoverageError,
)
from larp_audio_mvp.subtitles.validation import (
    SUBTITLE_SCHEMA_VERSION,
    calculate_grammar_quality,
    calculate_subtitle_diagnostics,
    validate_subtitle_document,
)
from larp_audio_mvp.subtitles.policy import (
    BoundarySignals,
    SEMANTIC_MAX_VISIBLE_CHARACTERS,
    SEMANTIC_MAX_WORDS,
    crosses_boundary,
    semantic_boundary_signals,
    semantic_candidate_cost,
    word_keys,
)
from larp_audio_mvp.subtitles.display import subtitle_display_text
from larp_audio_mvp.subtitles.repair import repair_orphan_ranges
from larp_audio_mvp.subtitles.wrapping import layout_semantic_cue

@dataclass(frozen=True, slots=True)
class _Candidate:
    start_word: int
    end_word: int
    cost: int


@dataclass(frozen=True, slots=True)
class SegmentationMetrics:
    """Portable proof of bounded phrase selection and measured sub-phases."""

    script_words: int
    candidate_evaluations: int
    hard_boundaries: int
    dramatic_anchors: int
    tokenization_nanoseconds: int
    candidate_boundary_detection_nanoseconds: int
    segmentation_nanoseconds: int
    timing_application_nanoseconds: int
    block_construction_nanoseconds: int
    validation_nanoseconds: int
    orphan_repair_nanoseconds: int = 0
    line_layout_nanoseconds: int = 0
    syntax_analyzer_mode: str = ""
    parser_initialization_nanoseconds: int = 0
    syntax_parse_nanoseconds: int = 0
    candidate_boundary_count: int = 0
    legal_boundary_count: int = 0
    discouraged_boundary_count: int = 0
    forbidden_boundary_count: int = 0
    forced_syntax_split_count: int = 0


class DeterministicSubtitleChunker:
    """Use linear-space, width-three DP without consulting recognition text."""

    def chunk(
        self,
        alignment: AlignmentResult,
        *,
        settings: SubtitleSettings,
        source_alignment_sha256: str,
    ) -> SubtitleDocument:
        document, _ = self.chunk_with_metrics(
            alignment,
            settings=settings,
            source_alignment_sha256=source_alignment_sha256,
        )
        return document

    def chunk_with_metrics(
        self,
        alignment: AlignmentResult,
        *,
        settings: SubtitleSettings,
        source_alignment_sha256: str,
    ) -> tuple[SubtitleDocument, SegmentationMetrics]:
        validate_alignment_result(alignment)
        if not alignment.diagnostics.provenance_complete:
            raise SubtitleCoverageError(
                "alignment ASR provenance is incomplete",
                code="INCOMPLETE_ALIGNMENT_PROVENANCE",
            )
        words = alignment.aligned_words
        if not words:
            raise SubtitleCoverageError(
                "alignment contains no script words",
                code="NO_SUBTITLE_WORDS",
            )
        if not any(word.timing_status is not TimingStatus.UNRESOLVED for word in words):
            raise SubtitleCoverageError(
                "all script words are unresolved; SRT timing cannot be invented",
                code="ALL_SUBTITLE_WORDS_UNRESOLVED",
            )

        keys = word_keys(words)
        exact_words = tuple(word.exact_text for word in words)
        signals = semantic_boundary_signals(
            alignment.script.exact_text, words, keys
        )
        boundaries, segmentation_metrics = self._segment_with_metrics(
            alignment, settings, signals=signals
        )
        repair_started = perf_counter_ns()
        mandatory_boundaries = frozenset(
            signals.required
        )

        def candidate_is_valid(start: int, end: int) -> bool:
            if end < len(words) and end in signals.grammar.syntax.forbidden_boundaries:
                return False
            return self._candidate(
                alignment,
                start,
                end,
                settings,
                keys=keys,
                exact_words=exact_words,
                signals=signals,
            ) is not None

        boundaries, _repair_metrics = repair_orphan_ranges(
            boundaries,
            keys=keys,
            protected=signals.grammar.protected,
            mandatory=mandatory_boundaries,
            candidate_is_valid=candidate_is_valid,
        )
        repair_elapsed = perf_counter_ns() - repair_started
        construction_started = perf_counter_ns()
        blocks = tuple(
            self._build_block(
                alignment,
                start,
                end,
                block_index=index,
                settings=settings,
                protected_boundaries=frozenset(
                    position - start
                    for position in signals.grammar.protected
                    if start < position < end
                ),
            )
            for index, (start, end) in enumerate(boundaries, start=1)
        )
        construction_elapsed = perf_counter_ns() - construction_started
        unresolved_count = sum(
            word.timing_status is TimingStatus.UNRESOLVED for word in words
        )
        interpolated_count = sum(
            word.timing_status is TimingStatus.INTERPOLATED for word in words
        )
        document_warnings: list[str] = []
        document_warnings.extend(signals.grammar.syntax.warnings)
        document_warnings.extend(self._semantic_degeneracy_warnings(blocks))
        grammar_quality = calculate_grammar_quality(
            alignment.script.exact_text, blocks
        )
        if grammar_quality.list_item_merge_violation_count:
            document_warnings.append(
                "one or more detected list items were merged"
            )
        if grammar_quality.protected_unit_violation_count:
            document_warnings.append(
                "one or more protected grammatical units required a forced split"
            )
        timing_coverage = Fraction(len(words) - unresolved_count, len(words))
        if timing_coverage < Fraction(
            settings.minimum_timing_coverage_for_export
        ):
            document_warnings.append(
                "timing coverage is below minimum_timing_coverage_for_export"
            )
        if unresolved_count:
            document_warnings.append(
                "unresolved script words were attached without fabricated word timing"
            )
        if interpolated_count:
            document_warnings.append(
                "interpolated script timing is present and remains explicitly marked"
            )
        document_warnings = sorted(set(document_warnings))
        diagnostics = calculate_subtitle_diagnostics(
            blocks=blocks,
            total_script_words=len(words),
            unresolved_script_words=unresolved_count,
            interpolated_script_words=interpolated_count,
            sample_rate=alignment.sample_rate,
            settings=settings,
            document_warnings=tuple(document_warnings),
            exact_script_text=alignment.script.exact_text,
            grammar_policy=True,
            layout_policy=True,
        )
        document = SubtitleDocument(
            schema_version=SUBTITLE_SCHEMA_VERSION,
            source_alignment_schema_version=alignment.schema_version,
            source_alignment_sha256=source_alignment_sha256,
            script_sha256=alignment.script.source_sha256,
            script_encoding=alignment.script.encoding,
            script_has_bom=alignment.script.has_bom,
            exact_script_text=alignment.script.exact_text,
            sample_rate=alignment.sample_rate,
            cleaned_total_samples=alignment.edit_map.output_total_samples,
            original_total_samples=alignment.edit_map.source_total_samples,
            configuration_snapshot=settings.snapshot(),
            blocks=blocks,
            diagnostics=diagnostics,
            warnings=tuple(document_warnings),
        )
        validation_started = perf_counter_ns()
        validate_subtitle_document(document)
        validation_elapsed = perf_counter_ns() - validation_started
        return document, SegmentationMetrics(
            script_words=segmentation_metrics.script_words,
            candidate_evaluations=segmentation_metrics.candidate_evaluations,
            hard_boundaries=segmentation_metrics.hard_boundaries,
            dramatic_anchors=segmentation_metrics.dramatic_anchors,
            tokenization_nanoseconds=segmentation_metrics.tokenization_nanoseconds,
            candidate_boundary_detection_nanoseconds=(
                segmentation_metrics.candidate_boundary_detection_nanoseconds
            ),
            segmentation_nanoseconds=segmentation_metrics.segmentation_nanoseconds,
            timing_application_nanoseconds=construction_elapsed,
            block_construction_nanoseconds=construction_elapsed,
            validation_nanoseconds=validation_elapsed,
            orphan_repair_nanoseconds=repair_elapsed,
            line_layout_nanoseconds=construction_elapsed,
            syntax_analyzer_mode=segmentation_metrics.syntax_analyzer_mode,
            parser_initialization_nanoseconds=segmentation_metrics.parser_initialization_nanoseconds,
            syntax_parse_nanoseconds=segmentation_metrics.syntax_parse_nanoseconds,
            candidate_boundary_count=segmentation_metrics.candidate_boundary_count,
            legal_boundary_count=segmentation_metrics.legal_boundary_count,
            discouraged_boundary_count=segmentation_metrics.discouraged_boundary_count,
            forbidden_boundary_count=segmentation_metrics.forbidden_boundary_count,
            forced_syntax_split_count=segmentation_metrics.forced_syntax_split_count,
        )

    def _segment(
        self, alignment: AlignmentResult, settings: SubtitleSettings
    ) -> tuple[tuple[int, int], ...]:
        boundaries, _ = self._segment_with_metrics(alignment, settings)
        return boundaries

    def _segment_with_metrics(
        self,
        alignment: AlignmentResult,
        settings: SubtitleSettings,
        *,
        signals: BoundarySignals | None = None,
    ) -> tuple[tuple[tuple[int, int], ...], SegmentationMetrics]:
        word_count = len(alignment.aligned_words)
        tokenization_started = perf_counter_ns()
        keys = word_keys(alignment.aligned_words)
        exact_words = tuple(word.exact_text for word in alignment.aligned_words)
        tokenization_elapsed = perf_counter_ns() - tokenization_started
        detection_started = perf_counter_ns()
        signals = signals or semantic_boundary_signals(
            alignment.script.exact_text, alignment.aligned_words, keys
        )
        mandatory_boundaries = frozenset(
            signals.required
        )
        detection_elapsed = perf_counter_ns() - detection_started
        segmentation_started = perf_counter_ns()
        def solve(*, allow_forbidden: bool) -> tuple[tuple[tuple[int, int], ...] | None, int]:
            infinity = 10**18
            costs = [infinity] * (word_count + 1)
            block_counts = [word_count + 1] * (word_count + 1)
            previous_start = [-1] * (word_count + 1)
            costs[0] = 0
            block_counts[0] = 0
            cells = 0
            for start in range(word_count):
                if costs[start] == infinity:
                    continue
                maximum_end = min(
                    word_count,
                    start + SEMANTIC_MAX_WORDS,
                )
                for end in range(start + 1, maximum_end + 1):
                    source_start, source_end = self._source_span(
                        alignment, start, end
                    )
                    if len(
                        subtitle_display_text(
                            alignment.script.exact_text[source_start:source_end]
                        )
                    ) > SEMANTIC_MAX_VISIBLE_CHARACTERS:
                        # Adding another word cannot shorten the display text,
                        # so the remaining look-ahead is provably infeasible.
                        break
                    cells += 1
                    if cells > settings.max_segmentation_cells:
                        raise SubtitleComplexityLimitError(
                            "subtitle segmentation exceeded "
                            f"max_segmentation_cells={settings.max_segmentation_cells}",
                            code="SUBTITLE_SEGMENTATION_LIMIT_EXCEEDED",
                        )
                    if crosses_boundary(start, end, mandatory_boundaries):
                        continue
                    if (
                        not allow_forbidden
                        and end < word_count
                        and end in signals.grammar.syntax.forbidden_boundaries
                    ):
                        continue
                    candidate = self._candidate(
                        alignment,
                        start,
                        end,
                        settings,
                        keys=keys,
                        exact_words=exact_words,
                        signals=signals,
                    )
                    if candidate is None:
                        continue
                    # Minimum semantic cue count is the primary objective.
                    # Syntax and pause scores only choose placement among
                    # equally sparse valid segmentations.
                    choice = (
                        block_counts[start] + 1,
                        costs[start] + candidate.cost,
                        start,
                    )
                    current = (
                        block_counts[end],
                        costs[end],
                        previous_start[end],
                    )
                    if choice < current:
                        block_counts[end], costs[end], previous_start[end] = choice
            if costs[word_count] == infinity:
                return None, cells
            ranges: list[tuple[int, int]] = []
            cursor = word_count
            while cursor:
                start = previous_start[cursor]
                if start < 0:
                    return None, cells
                ranges.append((start, cursor))
                cursor = start
            ranges.reverse()
            return tuple(ranges), cells

        selected, cells = solve(allow_forbidden=False)
        if selected is None:
            selected, forced_cells = solve(allow_forbidden=True)
            cells += forced_cells
        if selected is None:
            raise SubtitleCoverageError(
                "script words cannot be covered within unresolved attachment limits",
                code="UNSAFE_UNRESOLVED_SUBTITLE_WORDS",
            )
        ranges = selected
        chosen_boundaries = frozenset(end for _start, end in ranges[:-1])
        forced_syntax_splits = len(
            chosen_boundaries & signals.grammar.syntax.forbidden_boundaries
        )
        segmentation_elapsed = perf_counter_ns() - segmentation_started
        return ranges, SegmentationMetrics(
            script_words=word_count,
            candidate_evaluations=cells,
            hard_boundaries=len(
                signals.required
            ),
            dramatic_anchors=0,
            tokenization_nanoseconds=tokenization_elapsed,
            candidate_boundary_detection_nanoseconds=detection_elapsed,
            segmentation_nanoseconds=segmentation_elapsed,
            timing_application_nanoseconds=0,
            block_construction_nanoseconds=0,
            validation_nanoseconds=0,
            syntax_analyzer_mode=signals.grammar.syntax.mode.value,
            parser_initialization_nanoseconds=signals.grammar.syntax.parser_initialization_nanoseconds,
            syntax_parse_nanoseconds=signals.grammar.syntax.parse_nanoseconds,
            candidate_boundary_count=max(0, word_count - 1),
            legal_boundary_count=len(signals.grammar.syntax.legal_boundaries),
            discouraged_boundary_count=len(signals.grammar.syntax.discouraged_boundaries),
            forbidden_boundary_count=len(signals.grammar.syntax.forbidden_boundaries),
            forced_syntax_split_count=forced_syntax_splits,
        )

    def _candidate(
        self,
        alignment: AlignmentResult,
        start: int,
        end: int,
        settings: SubtitleSettings,
        *,
        keys: tuple[str, ...],
        exact_words: tuple[str, ...],
        signals: BoundarySignals,
    ) -> _Candidate | None:
        words = alignment.aligned_words[start:end]
        unresolved = sum(
            word.timing_status is TimingStatus.UNRESOLVED for word in words
        )
        if unresolved and not settings.allow_unresolved_attachment:
            return None
        if unresolved > settings.max_unresolved_words_per_block:
            return None
        timed = tuple(
            word for word in words if word.timing_status is not TimingStatus.UNRESOLVED
        )
        if not timed:
            return None
        source_start, source_end = self._source_span(alignment, start, end)
        source = alignment.script.exact_text[source_start:source_end]
        display_text = subtitle_display_text(source)
        visible_with_spaces = len(display_text)
        if not display_text or visible_with_spaces > SEMANTIC_MAX_VISIBLE_CHARACTERS:
            return None
        if (
            timed[0].cleaned_start_sample is None
            or timed[-1].cleaned_end_sample is None
        ):
            raise SubtitleChunkingError(
                "resolved alignment word is missing cleaned timing",
                code="INVALID_ALIGNMENT_TIMING_FOR_SUBTITLES",
            )
        duration = timed[-1].cleaned_end_sample - timed[0].cleaned_start_sample
        if duration <= 0:
            return None
        # Keep the historical duration setting meaningful, but allow a small
        # deterministic tolerance so a compact natural phrase is not split by
        # minor timing jitter around the configured ceiling.
        if (
            settings.max_duration_ms < 7_000
            and
            duration * 1_000 * 10
            > settings.max_duration_ms * alignment.sample_rate * 11
        ):
            return None
        capacity = settings.max_lines * settings.max_characters_per_line
        overflow = max(0, visible_with_spaces - capacity)
        cost = semantic_candidate_cost(
            keys=keys,
            exact_words=exact_words,
            start=start,
            end=end,
            source_text=display_text,
            signals=signals,
        )
        cost += overflow * 2_000
        cost += unresolved * 1_500
        cost += sum(
            word.timing_status is TimingStatus.INTERPOLATED for word in words
        ) * 250
        # Text syntax is primary; existing aligned pauses are secondary.
        if end < len(alignment.aligned_words):
            left = alignment.aligned_words[end - 1]
            right = alignment.aligned_words[end]
            if left.cleaned_end_sample is not None and right.cleaned_start_sample is not None:
                gap_ms_scaled = (
                    right.cleaned_start_sample - left.cleaned_end_sample
                ) * 1_000
                if gap_ms_scaled >= settings.strong_gap_break_ms * alignment.sample_rate:
                    cost -= 4_000
                elif gap_ms_scaled >= settings.preferred_gap_break_ms * alignment.sample_rate:
                    cost -= 180
        return _Candidate(start_word=start, end_word=end, cost=cost)

    @staticmethod
    def _source_span(
        alignment: AlignmentResult, start: int, end: int
    ) -> tuple[int, int]:
        source_start = (
            0 if start == 0 else alignment.aligned_words[start].char_start
        )
        source_end = (
            len(alignment.script.exact_text)
            if end == len(alignment.aligned_words)
            else alignment.aligned_words[end].char_start
        )
        return source_start, source_end

    def _build_block(
        self,
        alignment: AlignmentResult,
        start: int,
        end: int,
        *,
        block_index: int,
        settings: SubtitleSettings,
        protected_boundaries: frozenset[int] = frozenset(),
    ) -> SubtitleBlock:
        words = alignment.aligned_words[start:end]
        source_start, source_end = self._source_span(alignment, start, end)
        source = alignment.script.exact_text[source_start:source_end]
        display_text = subtitle_display_text(source)
        if not display_text or len(display_text) > SEMANTIC_MAX_VISIBLE_CHARACTERS:
            raise SubtitleChunkingError(
                "subtitle display text is outside the 1..45 character contract",
                code="INVALID_SUBTITLE_DISPLAY_LENGTH",
            )
        lines = layout_semantic_cue(
            display_text,
            protected_boundaries=protected_boundaries,
        )
        timed = tuple(
            word for word in words if word.timing_status is not TimingStatus.UNRESOLVED
        )
        if not timed:
            raise SubtitleChunkingError(
                "subtitle block has no timing anchor",
                code="UNANCHORED_SUBTITLE_BLOCK",
            )
        first_timed = timed[0]
        last_timed = timed[-1]
        if (
            first_timed.cleaned_start_sample is None
            or first_timed.original_start_sample is None
            or last_timed.cleaned_end_sample is None
            or last_timed.original_end_sample is None
        ):
            raise SubtitleChunkingError(
                "resolved alignment word lacks dual-timeline timing",
                code="INVALID_ALIGNMENT_TIMING_FOR_SUBTITLES",
            )
        cleaned_start = first_timed.cleaned_start_sample
        cleaned_end = last_timed.cleaned_end_sample
        duration = cleaned_end - cleaned_start
        visible = len(display_text)
        interpolated = tuple(
            word.script_word_index
            for word in words
            if word.timing_status is TimingStatus.INTERPOLATED
        )
        unresolved = tuple(
            word.script_word_index
            for word in words
            if word.timing_status is TimingStatus.UNRESOLVED
        )
        provenance = self._provenance(words)
        warnings: list[str] = []
        if interpolated:
            warnings.append("block contains interpolated script timing")
        if unresolved:
            warnings.append(
                "block contains attached unresolved words without fabricated timing"
            )
        cps = Fraction(visible * alignment.sample_rate, duration)
        if cps > Fraction(settings.max_characters_per_second):
            warnings.append("block exceeds max_characters_per_second")
        if duration * 1_000 > settings.max_duration_ms * alignment.sample_rate:
            warnings.append("block exceeds max_duration_ms")
        covered_tokens = tuple(
            token
            for token in alignment.tokens
            if token.char_start >= source_start and token.char_end <= source_end
        )
        if not covered_tokens:
            raise SubtitleChunkingError(
                "subtitle source span contains no script token",
                code="INVALID_SUBTITLE_SOURCE_SPAN",
            )
        return SubtitleBlock(
            block_index=block_index,
            source_char_start=source_start,
            source_char_end=source_end,
            source_text_exact=source,
            display_lines=lines,
            first_token_index=covered_tokens[0].token_index,
            last_token_index=covered_tokens[-1].token_index,
            script_word_indices=tuple(
                word.script_word_index for word in words
            ),
            interpolated_script_word_indices=interpolated,
            unresolved_script_word_indices=unresolved,
            cleaned_start_sample=cleaned_start,
            cleaned_end_sample=cleaned_end,
            original_start_sample=first_timed.original_start_sample,
            original_end_sample=last_timed.original_end_sample,
            duration_samples=duration,
            word_count=len(words),
            visible_character_count=visible,
            characters_per_second=cps,
            timing_provenance=provenance,
            contains_interpolated_words=bool(interpolated),
            contains_unresolved_words=bool(unresolved),
            warnings=tuple(sorted(set(warnings))),
        )

    @staticmethod
    def _provenance(
        words: tuple[AlignedScriptWord, ...],
    ) -> SubtitleTimingProvenance:
        if any(word.timing_status is TimingStatus.UNRESOLVED for word in words):
            return SubtitleTimingProvenance.ANCHORED_WITH_UNRESOLVED
        interpolated = sum(
            word.timing_status is TimingStatus.INTERPOLATED for word in words
        )
        if interpolated == len(words):
            return SubtitleTimingProvenance.INTERPOLATED
        if interpolated:
            return SubtitleTimingProvenance.MIXED_OBSERVED_INTERPOLATED
        return SubtitleTimingProvenance.OBSERVED

    @staticmethod
    def _semantic_degeneracy_warnings(
        blocks: tuple[SubtitleBlock, ...],
    ) -> tuple[str, ...]:
        """Warn when ordinary prose collapses into mechanical short chunks."""

        ordinary = tuple(
            block
            for block in blocks
            if not block.source_text_exact.rstrip().endswith((",", ".", "?", "!", "…"))
        )
        if len(ordinary) < 6:
            return ()
        counts = tuple(block.word_count for block in ordinary)
        warnings: list[str] = []
        short_ratio = Fraction(sum(count <= 2 for count in counts), len(counts))
        if short_ratio > Fraction(1, 2):
            warnings.append(
                "ordinary prose contains excessive one- or two-word semantic blocks"
            )
        if sum(count == 2 for count in counts) * 5 >= len(counts) * 4:
            warnings.append("subtitle lengths show repeated two-word degeneration")
        if len(set(counts)) == 1:
            warnings.append("subtitle phrase lengths have no variation")
        return tuple(warnings)
