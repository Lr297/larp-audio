"""Strict semantic validation for canonical subtitle documents."""

from __future__ import annotations

import codecs
import hashlib
import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import (
    ScriptTokenKind,
    SubtitleBlock,
    SubtitleDiagnostics,
    SubtitleDocument,
    SubtitleTimingProvenance,
)
from larp_audio_mvp.core.errors import SubtitleTimingError, SubtitleValidationError
from larp_audio_mvp.subtitles.wrapping import non_whitespace_signature
from larp_audio_mvp.subtitles.policy import (
    LEGACY_GRAMMAR_SUBTITLE_POLICY_VERSION,
    LEGACY_ORPHAN_REPAIR_POLICY_VERSION,
    LEGACY_PERIOD_FREE_SUBTITLE_POLICY_VERSION,
    LEGACY_SYNTAX_SUBTITLE_POLICY_VERSION,
    LEGACY_SUBTITLE_POLICY_VERSION,
    LEGACY_SEMANTIC_SUBTITLE_POLICY_VERSION,
    LEGACY_SEMANTIC_MAX_VISIBLE_CHARACTERS,
    RAPID_MAX_WORDS,
    RAPID_SUBTITLE_POLICY_VERSION,
    SEMANTIC_MAX_VISIBLE_CHARACTERS,
    SEMANTIC_MAX_WORDS,
    SEMANTIC_SUBTITLE_POLICY_VERSION,
    hard_boundary_positions,
    semantic_boundary_signals,
    sentence_boundary_positions,
    word_keys,
)
from larp_audio_mvp.subtitles.grammar import (
    GrammarQualityMetrics,
    grammar_quality_metrics,
)
from larp_audio_mvp.subtitles.display import (
    has_removable_terminal_comma,
    has_removable_terminal_period,
    legacy_period_free_display_text,
    subtitle_display_text,
)
from larp_audio_mvp.subtitles.repair import (
    is_incomplete_boundary,
    orphan_fragment_count,
)
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing

SUBTITLE_SCHEMA_VERSION = "subtitle_blocks.schema.v1"
_SENTENCE_END = re.compile(r"(?:\.{3}|…|[.!?])(?:[\]\)}»”’]*)\s*$")
_COMMA_END = re.compile(r",(?:[\]\)}»”’]*)\s*$")


def settings_from_snapshot(
    snapshot: tuple[tuple[str, str], ...],
) -> SubtitleSettings:
    values = dict(snapshot)
    expected = {
        "allow_unresolved_attachment",
        "max_characters_per_line",
        "max_characters_per_second",
        "max_duration_ms",
        "max_lines",
        "max_segmentation_cells",
        "max_unresolved_words_per_block",
        "max_words_per_block",
        "minimum_timing_coverage_for_export",
        "new_block_penalty",
        "policy_version",
        "preferred_gap_break_ms",
        "preferred_min_duration_ms",
        "preferred_min_visible_chars",
        "preferred_min_words_per_block",
        "short_block_penalty",
        "single_word_block_penalty",
        "strong_gap_break_ms",
    }
    policy_version = values.get("policy_version")
    if set(values) != expected or policy_version not in {
        LEGACY_SUBTITLE_POLICY_VERSION,
        RAPID_SUBTITLE_POLICY_VERSION,
        LEGACY_SEMANTIC_SUBTITLE_POLICY_VERSION,
        LEGACY_PERIOD_FREE_SUBTITLE_POLICY_VERSION,
        LEGACY_GRAMMAR_SUBTITLE_POLICY_VERSION,
        LEGACY_ORPHAN_REPAIR_POLICY_VERSION,
        LEGACY_SYNTAX_SUBTITLE_POLICY_VERSION,
        SEMANTIC_SUBTITLE_POLICY_VERSION,
    }:
        raise SubtitleValidationError(
            "subtitle configuration snapshot is unsupported or incomplete",
            code="INVALID_SUBTITLE_CONFIGURATION",
        )
    try:
        if values["allow_unresolved_attachment"] not in {"true", "false"}:
            raise ValueError("invalid boolean")
        return SubtitleSettings(
            max_lines=int(values["max_lines"]),
            max_characters_per_line=int(values["max_characters_per_line"]),
            max_words_per_block=int(values["max_words_per_block"]),
            min_duration_ms=int(values["preferred_min_duration_ms"]),
            max_duration_ms=int(values["max_duration_ms"]),
            max_characters_per_second=Decimal(
                values["max_characters_per_second"]
            ),
            preferred_gap_break_ms=int(values["preferred_gap_break_ms"]),
            strong_gap_break_ms=int(values["strong_gap_break_ms"]),
            preferred_min_words_per_block=int(
                values["preferred_min_words_per_block"]
            ),
            preferred_min_visible_chars=int(
                values["preferred_min_visible_chars"]
            ),
            new_block_penalty=int(values["new_block_penalty"]),
            single_word_block_penalty=int(
                values["single_word_block_penalty"]
            ),
            short_block_penalty=int(values["short_block_penalty"]),
            max_unresolved_words_per_block=int(
                values["max_unresolved_words_per_block"]
            ),
            minimum_timing_coverage_for_export=Decimal(
                values["minimum_timing_coverage_for_export"]
            ),
            allow_unresolved_attachment=(
                values["allow_unresolved_attachment"] == "true"
            ),
            max_segmentation_cells=int(values["max_segmentation_cells"]),
            _allow_legacy_word_limit=(
                policy_version not in {
                    SEMANTIC_SUBTITLE_POLICY_VERSION,
                    LEGACY_ORPHAN_REPAIR_POLICY_VERSION,
                    LEGACY_GRAMMAR_SUBTITLE_POLICY_VERSION,
                    LEGACY_PERIOD_FREE_SUBTITLE_POLICY_VERSION,
                }
            ),
        )
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise SubtitleValidationError(
            "subtitle configuration snapshot contains invalid values",
            code="INVALID_SUBTITLE_CONFIGURATION",
        ) from exc


def calculate_subtitle_diagnostics(
    *,
    blocks: tuple[SubtitleBlock, ...],
    total_script_words: int,
    unresolved_script_words: int,
    interpolated_script_words: int,
    sample_rate: int,
    settings: SubtitleSettings,
    document_warnings: tuple[str, ...],
    exact_script_text: str | None = None,
    grammar_policy: bool = False,
    layout_policy: bool = False,
) -> SubtitleDiagnostics:
    block_count = len(blocks)
    exported_indices = {
        index for block in blocks for index in block.script_word_indices
    }
    attached_unresolved = sum(
        len(block.unresolved_script_word_indices) for block in blocks
    )
    total_duration_samples = sum(block.duration_samples for block in blocks)
    average_duration = (
        Fraction(total_duration_samples, block_count * sample_rate)
        if block_count
        else Fraction(0)
    )
    maximum_duration = (
        max((Fraction(block.duration_samples, sample_rate) for block in blocks), default=Fraction(0))
    )
    average_cps = (
        sum((block.characters_per_second for block in blocks), Fraction(0))
        / block_count
        if block_count
        else Fraction(0)
    )
    maximum_cps = max(
        (block.characters_per_second for block in blocks), default=Fraction(0)
    )
    cps_limit = Fraction(settings.max_characters_per_second)
    text_coverage = (
        Fraction(len(exported_indices), total_script_words)
        if total_script_words
        else Fraction(0)
    )
    timing_coverage = (
        Fraction(total_script_words - unresolved_script_words, total_script_words)
        if total_script_words
        else Fraction(0)
    )
    srt_exportable = bool(blocks) and text_coverage == 1 and (
        timing_coverage >= Fraction(settings.minimum_timing_coverage_for_export)
    )
    word_counts = tuple(block.word_count for block in blocks)
    single_word_blocks = sum(count == 1 for count in word_counts)
    short_blocks = sum(
        block.word_count < settings.preferred_min_words_per_block
        or block.visible_character_count < settings.preferred_min_visible_chars
        or block.duration_samples * 1_000 < settings.min_duration_ms * sample_rate
        for block in blocks
    )
    sentence_boundaries = sum(
        bool(_SENTENCE_END.search(block.source_text_exact))
        for block in blocks[:-1]
    )
    comma_boundaries = sum(
        bool(_COMMA_END.search(block.source_text_exact))
        for block in blocks[:-1]
    )
    gap_boundaries = sum(
        (right.cleaned_start_sample - left.cleaned_end_sample) * 1_000
        >= settings.preferred_gap_break_ms * sample_rate
        for left, right in zip(blocks, blocks[1:])
    )
    forced_boundaries = sum(
        left.word_count + right.word_count > settings.max_words_per_block
        or (right.cleaned_end_sample - left.cleaned_start_sample) * 1_000
        > settings.max_duration_ms * sample_rate
        for left, right in zip(blocks, blocks[1:])
    )
    grammar = (
        calculate_grammar_quality(exact_script_text, blocks)
        if grammar_policy and exact_script_text is not None
        else GrammarQualityMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    )
    ranges = tuple(
        (block.script_word_indices[0], block.script_word_indices[-1] + 1)
        for block in blocks
    )
    keys: tuple[str, ...] = ()
    grammar_signals = None
    if grammar_policy and exact_script_text is not None:
        tokens = tokenize_script(exact_script_text)
        script_words = tuple(
            token for token in tokens if token.kind is ScriptTokenKind.WORD
        )
        keys = word_keys(script_words)
        grammar_signals = semantic_boundary_signals(
            exact_script_text, script_words, keys
        ).grammar
    block_boundaries = frozenset(
        left.script_word_indices[-1] + 1 for left in blocks[:-1]
    )
    required_boundaries = (
        frozenset(
            grammar_signals.syntax.sentence_boundaries
            | grammar_signals.list_item
        )
        if grammar_signals is not None
        else frozenset()
    )
    unnecessary_splits = (
        sum(
            boundary not in required_boundaries
            and len(
                subtitle_display_text(
                    left.source_text_exact + right.source_text_exact
                )
            )
            <= SEMANTIC_MAX_VISIBLE_CHARACTERS
            for boundary, (left, right) in zip(
                sorted(block_boundaries), zip(blocks, blocks[1:])
            )
        )
        if grammar_signals is not None
        else 0
    )
    incomplete_endings = (
        sum(
            (left.script_word_indices[-1] + 1) not in grammar_signals.list_item
            and is_incomplete_boundary(
                keys, left.script_word_indices[-1] + 1, grammar_signals.protected
            )
            and len(subtitle_display_text(left.source_text_exact + right.source_text_exact))
            <= SEMANTIC_MAX_VISIBLE_CHARACTERS
            for left, right in zip(blocks, blocks[1:])
        )
        if grammar_signals is not None
        else 0
    )
    orphan_fragments = (
        sum(
            right.word_count <= 3
            and (left.script_word_indices[-1] + 1) not in grammar_signals.list_item
            and is_incomplete_boundary(
                keys, left.script_word_indices[-1] + 1, grammar_signals.protected
            )
            and len(subtitle_display_text(left.source_text_exact + right.source_text_exact))
            <= SEMANTIC_MAX_VISIBLE_CHARACTERS
            for left, right in zip(blocks, blocks[1:])
        )
        if grammar_signals is not None
        else 0
    )
    return SubtitleDiagnostics(
        total_blocks=block_count,
        total_script_words=total_script_words,
        exported_script_words=len(exported_indices),
        unresolved_script_words=unresolved_script_words,
        attached_unresolved_words=attached_unresolved,
        interpolated_script_words=interpolated_script_words,
        blocks_with_interpolated_words=sum(
            block.contains_interpolated_words for block in blocks
        ),
        blocks_with_unresolved_words=sum(
            block.contains_unresolved_words for block in blocks
        ),
        average_block_duration=average_duration,
        maximum_block_duration=maximum_duration,
        average_characters_per_second=average_cps,
        maximum_characters_per_second=maximum_cps,
        blocks_over_cps_limit=sum(
            block.characters_per_second > cps_limit for block in blocks
        ),
        blocks_over_duration_limit=sum(
            block.duration_samples * 1_000
            > settings.max_duration_ms * sample_rate
            for block in blocks
        ),
        blocks_over_line_length_limit=sum(
            any(len(line) > settings.max_characters_per_line for line in block.display_lines)
            for block in blocks
        ),
        single_word_blocks=single_word_blocks,
        short_blocks=short_blocks,
        average_words_per_block=(
            Fraction(sum(word_counts), block_count) if block_count else Fraction(0)
        ),
        minimum_words_in_block=min(word_counts, default=0),
        maximum_words_in_block=max(word_counts, default=0),
        blocks_created_at_sentence_boundary=sentence_boundaries,
        blocks_created_at_comma_boundary=comma_boundaries,
        blocks_created_at_gap_boundary=gap_boundaries,
        blocks_forced_by_hard_limit=forced_boundaries,
        text_coverage=text_coverage,
        timing_coverage=timing_coverage,
        srt_exportable=srt_exportable,
        warnings_count=len(document_warnings)
        + sum(len(block.warnings) for block in blocks),
        internal_gap_count=0,
        srt_gap_count=0,
        overlap_count=0,
        maximum_internal_gap_ms=0,
        maximum_srt_gap_ms=0,
        list_item_count=grammar.list_item_count,
        list_item_merge_violation_count=grammar.list_item_merge_violation_count,
        protected_unit_count=grammar.protected_unit_count,
        protected_unit_violation_count=grammar.protected_unit_violation_count,
        adjective_noun_split_count=grammar.adjective_noun_split_count,
        verb_object_split_count=grammar.verb_object_split_count,
        phrasal_verb_split_count=grammar.phrasal_verb_split_count,
        preposition_object_split_count=grammar.preposition_object_split_count,
        number_unit_split_count=grammar.number_unit_split_count,
        product_name_split_count=grammar.product_name_split_count,
        maximum_display_characters=(
            max((len(block.display_text) for block in blocks), default=0)
            if grammar_policy
            else 0
        ),
        orphan_fragment_count=orphan_fragments if layout_policy else 0,
        incomplete_ending_count=incomplete_endings if layout_policy else 0,
        trailing_period_violation_count=(
            sum(has_removable_terminal_period(block.display_text_plain) for block in blocks)
            if layout_policy else 0
        ),
        trailing_comma_violation_count=(
            sum(has_removable_terminal_comma(block.display_text_plain) for block in blocks)
            if layout_policy else 0
        ),
        three_line_cue_count=(
            sum(len(block.display_lines) >= 3 for block in blocks)
            if layout_policy else 0
        ),
        empty_line_count=(
            sum(
                not line or line != line.strip()
                for block in blocks
                for line in block.display_lines
            )
            if layout_policy else 0
        ),
        maximum_plain_characters=(
            max((len(block.display_text_plain) for block in blocks), default=0)
            if layout_policy else 0
        ),
        maximum_render_line_characters=(
            max((len(line) for block in blocks for line in block.display_lines), default=0)
            if layout_policy else 0
        ),
        cue_count=block_count if layout_policy else 0,
        two_line_cue_count=(
            sum(len(block.display_lines) == 2 for block in blocks)
            if layout_policy else 0
        ),
        forced_syntax_split_count=grammar.forced_syntax_split_count,
        auxiliary_verb_split_count=grammar.auxiliary_verb_split_count,
        verb_particle_split_count=grammar.verb_particle_split_count,
        compound_noun_split_count=grammar.compound_noun_split_count,
        degree_modifier_split_count=grammar.degree_modifier_split_count,
        temporal_connector_split_count=grammar.temporal_connector_split_count,
        proper_name_split_count=grammar.proper_name_split_count,
        semantic_cue_count=block_count if layout_policy else 0,
        unnecessary_split_count=unnecessary_splits if layout_policy else 0,
        required_boundary_miss_count=(
            len(required_boundaries - block_boundaries)
            if layout_policy
            else 0
        ),
        list_item_internal_split_count=(
            len(block_boundaries & grammar_signals.protected)
            if layout_policy
            and grammar_signals is not None
            and grammar_signals.list_item
            else 0
        ),
        orphan_beginning_count=orphan_fragments if layout_policy else 0,
        wh_clause_split_count=grammar.wh_clause_split_count,
        or_not_split_count=grammar.or_not_split_count,
        parser_low_confidence_split_count=(
            unnecessary_splits
            if layout_policy
            and grammar_signals is not None
            and grammar_signals.syntax.mode.value == "deterministic_fallback"
            else 0
        ),
    )


def calculate_grammar_quality(
    exact_script_text: str, blocks: tuple[SubtitleBlock, ...]
) -> GrammarQualityMetrics:
    tokens = tokenize_script(exact_script_text)
    words = tuple(token for token in tokens if token.kind is ScriptTokenKind.WORD)
    keys = word_keys(words)
    signals = semantic_boundary_signals(exact_script_text, words, keys).grammar
    boundaries = frozenset(
        block.script_word_indices[-1] + 1 for block in blocks[:-1]
    )
    return grammar_quality_metrics(signals, boundaries)


def _expected_provenance(block: SubtitleBlock) -> SubtitleTimingProvenance:
    if block.unresolved_script_word_indices:
        return SubtitleTimingProvenance.ANCHORED_WITH_UNRESOLVED
    if block.interpolated_script_word_indices:
        if len(block.interpolated_script_word_indices) == block.word_count:
            return SubtitleTimingProvenance.INTERPOLATED
        return SubtitleTimingProvenance.MIXED_OBSERVED_INTERPOLATED
    return SubtitleTimingProvenance.OBSERVED


def validate_subtitle_document(document: SubtitleDocument) -> None:
    """Recalculate every portable invariant required by downstream exporters."""

    try:
        if document.schema_version != SUBTITLE_SCHEMA_VERSION:
            raise SubtitleValidationError(
                "unsupported subtitle schema version",
                code="UNSUPPORTED_SUBTITLE_SCHEMA",
            )
        settings = settings_from_snapshot(document.configuration_snapshot)
        prefix = codecs.BOM_UTF8 if document.script_has_bom else b""
        expected_script_hash = hashlib.sha256(
            prefix + document.exact_script_text.encode("utf-8")
        ).hexdigest()
        if document.script_sha256 != expected_script_hash:
            raise SubtitleValidationError(
                "subtitle script hash does not match exact text",
                code="SUBTITLE_SCRIPT_HASH_MISMATCH",
            )
        tokens = tokenize_script(document.exact_script_text)
        word_tokens = tuple(
            token for token in tokens if token.kind is ScriptTokenKind.WORD
        )
        if not word_tokens:
            raise SubtitleValidationError(
                "subtitle script contains no word token",
                code="SUBTITLE_SCRIPT_EMPTY",
            )
        word_index_by_token = {
            token.token_index: index for index, token in enumerate(word_tokens)
        }
        policy_version = dict(document.configuration_snapshot)["policy_version"]
        rapid_policy = policy_version == RAPID_SUBTITLE_POLICY_VERSION
        semantic_policy = policy_version == SEMANTIC_SUBTITLE_POLICY_VERSION
        legacy_orphan_policy = policy_version == LEGACY_ORPHAN_REPAIR_POLICY_VERSION
        legacy_grammar_policy = (
            policy_version == LEGACY_GRAMMAR_SUBTITLE_POLICY_VERSION
        )
        legacy_period_free_policy = (
            policy_version == LEGACY_PERIOD_FREE_SUBTITLE_POLICY_VERSION
        )
        display_policy = (
            semantic_policy or legacy_orphan_policy or legacy_grammar_policy or legacy_period_free_policy
        )
        legacy_semantic_policy = (
            policy_version == LEGACY_SEMANTIC_SUBTITLE_POLICY_VERSION
        )
        semantic_signals = semantic_boundary_signals(
            document.exact_script_text, word_tokens, word_keys(word_tokens)
        )
        mandatory_boundaries = (
            hard_boundary_positions(document.exact_script_text, word_tokens)
            if rapid_policy
            else semantic_signals.required
            if semantic_policy or legacy_orphan_policy or legacy_grammar_policy
            else sentence_boundary_positions(document.exact_script_text, word_tokens)
            if display_policy or legacy_semantic_policy
            else frozenset()
        )
        cursor = 0
        previous_cleaned_end = -1
        previous_original_end = -1
        all_word_indices: list[int] = []
        for expected_index, block in enumerate(document.blocks, start=1):
            if block.block_index != expected_index:
                raise SubtitleValidationError(
                    "subtitle block indices are not sequential",
                    code="INVALID_SUBTITLE_BLOCK_INDEX",
                )
            if rapid_policy and not (1 <= block.word_count <= RAPID_MAX_WORDS):
                raise SubtitleValidationError(
                    "rapid subtitle block must contain exactly 1..3 script words",
                    code="INVALID_RAPID_SUBTITLE_WORD_COUNT",
                )
            if rapid_policy and any(
                position in mandatory_boundaries
                for position in range(
                    block.script_word_indices[0] + 1,
                    block.script_word_indices[-1] + 1,
                )
            ):
                raise SubtitleValidationError(
                    "rapid subtitle block crosses a mandatory punctuation boundary",
                    code="INVALID_RAPID_SUBTITLE_BOUNDARY",
                )
            if (display_policy or legacy_semantic_policy) and not (
                1 <= block.word_count <= SEMANTIC_MAX_WORDS
            ):
                raise SubtitleValidationError(
                    "semantic subtitle block must contain 1..10 script words",
                    code="INVALID_SEMANTIC_SUBTITLE_WORD_COUNT",
                )
            if (
                display_policy
                and len(block.display_text) > SEMANTIC_MAX_VISIBLE_CHARACTERS
            ):
                raise SubtitleValidationError(
                    "semantic subtitle block exceeds the visible-character safety ceiling",
                    code="INVALID_SEMANTIC_SUBTITLE_LENGTH",
                )
            if (
                legacy_semantic_policy
                and block.word_count > 1
                and len(block.source_text_exact.strip())
                > LEGACY_SEMANTIC_MAX_VISIBLE_CHARACTERS
            ):
                raise SubtitleValidationError(
                    "legacy semantic subtitle block exceeds its 60-character ceiling",
                    code="INVALID_SEMANTIC_SUBTITLE_LENGTH",
                )
            if (display_policy or legacy_semantic_policy) and any(
                position in mandatory_boundaries
                for position in range(
                    block.script_word_indices[0] + 1,
                    block.script_word_indices[-1] + 1,
                )
            ):
                raise SubtitleValidationError(
                    "semantic subtitle block crosses a sentence boundary",
                    code="INVALID_SEMANTIC_SUBTITLE_BOUNDARY",
                )
            if block.source_char_start != cursor:
                raise SubtitleValidationError(
                    "subtitle source spans are not contiguous",
                    code="INVALID_SUBTITLE_CHAR_SPAN",
                )
            if document.exact_script_text[
                block.source_char_start : block.source_char_end
            ] != block.source_text_exact:
                raise SubtitleValidationError(
                    "subtitle block does not match its exact source span",
                    code="INVALID_SUBTITLE_CHAR_SPAN",
                )
            covered_tokens = tuple(
                token
                for token in tokens
                if token.char_start >= block.source_char_start
                and token.char_end <= block.source_char_end
            )
            if (
                not covered_tokens
                or covered_tokens[0].token_index != block.first_token_index
                or covered_tokens[-1].token_index != block.last_token_index
            ):
                raise SubtitleValidationError(
                    "subtitle token bounds do not match source span",
                    code="INVALID_SUBTITLE_TOKEN_SPAN",
                )
            expected_words = tuple(
                word_index_by_token[token.token_index]
                for token in covered_tokens
                if token.kind is ScriptTokenKind.WORD
            )
            if expected_words != block.script_word_indices:
                raise SubtitleValidationError(
                    "subtitle word indices do not match source span",
                    code="INVALID_SUBTITLE_WORD_COVERAGE",
                )
            if len(block.display_lines) > settings.max_lines:
                raise SubtitleValidationError(
                    "subtitle block exceeds max_lines",
                    code="INVALID_SUBTITLE_LAYOUT",
                )
            if display_policy:
                expected_display = (
                    subtitle_display_text(block.source_text_exact)
                    if semantic_policy or legacy_orphan_policy
                    else legacy_period_free_display_text(block.source_text_exact)
                )
                if (
                    " ".join(block.display_lines) != expected_display
                    or not 1 <= len(block.display_text) <= SEMANTIC_MAX_VISIBLE_CHARACTERS
                    or block.display_text != block.display_text.strip()
                    or "\n" in block.display_text
                    or "\r" in block.display_text
                    or has_removable_terminal_period(block.display_text)
                    or (semantic_policy or legacy_orphan_policy) and has_removable_terminal_comma(block.display_text)
                    or (semantic_policy or legacy_orphan_policy) and len(block.display_lines) > 2
                    or any(not line or line != line.strip() for line in block.display_lines)
                    or (not semantic_policy and block.display_lines != (expected_display,))
                ):
                    raise SubtitleValidationError(
                        "subtitle display text violates the period-free display contract",
                        code="SUBTITLE_TEXT_CHANGED",
                    )
                visible = len(block.display_text)
            else:
                if non_whitespace_signature("\n".join(block.display_lines)) != (
                    non_whitespace_signature(block.source_text_exact)
                ):
                    raise SubtitleValidationError(
                        "subtitle display text changed source content",
                        code="SUBTITLE_TEXT_CHANGED",
                    )
                visible = len(non_whitespace_signature(block.source_text_exact))
            expected_cps = Fraction(
                visible * document.sample_rate, block.duration_samples
            )
            if (
                block.visible_character_count != visible
                or block.characters_per_second != expected_cps
            ):
                raise SubtitleValidationError(
                    "subtitle visible-character/CPS values are inconsistent",
                    code="INVALID_SUBTITLE_CPS",
                )
            if block.timing_provenance is not _expected_provenance(block):
                raise SubtitleValidationError(
                    "subtitle timing provenance is inconsistent",
                    code="INVALID_SUBTITLE_PROVENANCE",
                )
            if len(block.unresolved_script_word_indices) > (
                settings.max_unresolved_words_per_block
            ):
                raise SubtitleValidationError(
                    "subtitle block exceeds unresolved attachment limit",
                    code="INVALID_UNRESOLVED_ATTACHMENT",
                )
            if block.unresolved_script_word_indices and not (
                settings.allow_unresolved_attachment
            ):
                raise SubtitleValidationError(
                    "subtitle configuration forbids unresolved attachment",
                    code="INVALID_UNRESOLVED_ATTACHMENT",
                )
            if (
                block.cleaned_end_sample > document.cleaned_total_samples
                or block.original_end_sample > document.original_total_samples
                or block.cleaned_start_sample < previous_cleaned_end
                or block.original_start_sample < previous_original_end
            ):
                raise SubtitleValidationError(
                    "subtitle block timing is out of range or overlapping",
                    code="INVALID_SUBTITLE_TIMING",
                )
            if block.warnings != tuple(sorted(set(block.warnings))):
                raise SubtitleValidationError(
                    "subtitle block warnings must be sorted and unique",
                    code="INVALID_SUBTITLE_WARNINGS",
                )
            all_word_indices.extend(block.script_word_indices)
            cursor = block.source_char_end
            previous_cleaned_end = block.cleaned_end_sample
            previous_original_end = block.original_end_sample
        if cursor != len(document.exact_script_text):
            raise SubtitleValidationError(
                "subtitle blocks do not cover exact script text",
                code="INVALID_SUBTITLE_CHAR_SPAN",
            )
        if tuple(all_word_indices) != tuple(range(len(word_tokens))):
            raise SubtitleValidationError(
                "subtitle words are missing, duplicated, or reordered",
                code="INVALID_SUBTITLE_WORD_COVERAGE",
            )
        if semantic_policy:
            boundaries = frozenset(
                block.script_word_indices[-1] + 1 for block in document.blocks[:-1]
            )
            incomplete = {
                left.script_word_indices[-1] + 1
                for left, right in zip(document.blocks, document.blocks[1:])
                if (left.script_word_indices[-1] + 1) not in semantic_signals.required
                and is_incomplete_boundary(
                    word_keys(word_tokens),
                    left.script_word_indices[-1] + 1,
                    semantic_signals.grammar.protected,
                )
                and len(
                    subtitle_display_text(
                        left.source_text_exact + right.source_text_exact
                    )
                )
                <= SEMANTIC_MAX_VISIBLE_CHARACTERS
            }
            if incomplete:
                raise SubtitleValidationError(
                    "subtitle blocks contain an incomplete or protected boundary",
                    code="INVALID_SUBTITLE_ORPHAN_BOUNDARY",
                )
        timing = apply_gapless_display_timing(document)
        if len(timing) != len(document.blocks):
            raise SubtitleValidationError(
                "canonical gapless timing does not cover every subtitle block",
                code="INVALID_SUBTITLE_TIMING",
            )
        if document.warnings != tuple(sorted(set(document.warnings))):
            raise SubtitleValidationError(
                "subtitle document warnings must be sorted and unique",
                code="INVALID_SUBTITLE_WARNINGS",
            )
        unresolved = {
            index
            for block in document.blocks
            for index in block.unresolved_script_word_indices
        }
        interpolated = {
            index
            for block in document.blocks
            for index in block.interpolated_script_word_indices
        }
        if unresolved & interpolated:
            raise SubtitleValidationError(
                "a word cannot be both unresolved and interpolated",
                code="INVALID_SUBTITLE_PROVENANCE",
            )
        recalculated = calculate_subtitle_diagnostics(
            blocks=document.blocks,
            total_script_words=len(word_tokens),
            unresolved_script_words=len(unresolved),
            interpolated_script_words=len(interpolated),
            sample_rate=document.sample_rate,
            settings=settings,
            document_warnings=document.warnings,
            exact_script_text=document.exact_script_text,
            grammar_policy=semantic_policy or legacy_orphan_policy or legacy_grammar_policy,
            layout_policy=semantic_policy or legacy_orphan_policy,
        )
        if recalculated != document.diagnostics:
            raise SubtitleValidationError(
                "subtitle diagnostics do not match recalculated values",
                code="SUBTITLE_DIAGNOSTICS_MISMATCH",
            )
    except SubtitleValidationError:
        raise
    except SubtitleTimingError as exc:
        raise SubtitleValidationError(str(exc), code=exc.code) from exc
    except Exception as exc:
        raise SubtitleValidationError(
            "subtitle document validation failed",
            code="INVALID_SUBTITLE_DOCUMENT",
        ) from exc
