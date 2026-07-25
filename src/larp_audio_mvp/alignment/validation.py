"""Strict semantic validation for standalone alignment schema v2 artifacts."""

from __future__ import annotations

import codecs
import hashlib
import re
from collections import defaultdict
from fractions import Fraction
from decimal import Decimal, InvalidOperation
from typing import Sequence

from larp_audio_mvp.alignment.engine import string_similarity
from larp_audio_mvp.alignment.normalizer import comparison_key, structural_key
from larp_audio_mvp.alignment.script import count_script_lines
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.core.contracts import (
    AlignedScriptWord,
    AlignmentDiagnostics,
    AlignmentMatchType,
    AlignmentResult,
    RejectedAsrEvidence,
    TimingStatus,
)
from larp_audio_mvp.core.errors import AlignmentValidationError, ConfigurationError
from larp_audio_mvp.core.timeline import TimelineMapper
from larp_audio_mvp.config import AlignmentSettings

ALIGNMENT_SCHEMA_VERSION = "alignment.schema.v2"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OPERATION_ID = re.compile(r"alignment-op-[0-9]{6}")
_ACCEPTED_TYPES = frozenset(
    {
        AlignmentMatchType.EXACT,
        AlignmentMatchType.NORMALIZED,
        AlignmentMatchType.FUZZY,
        AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR,
        AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR,
    }
)
_ANCHOR_TYPES = _ACCEPTED_TYPES - {AlignmentMatchType.FUZZY}


def validate_alignment_result(result: AlignmentResult) -> None:
    """Reject any structural, temporal, diagnostic, or provenance inconsistency."""

    settings = _settings_from_snapshot(result)
    _validate_script(result)
    _validate_timelines(result)
    _validate_aligned_words(result, settings)
    _validate_provenance(result)
    recalculated = calculate_alignment_diagnostics(
        result.aligned_words,
        total_asr_words=len(result.recognition.words),
        unmatched_asr_words=len(result.unmatched_asr_words),
        rejected_asr_evidence=result.rejected_asr_evidence,
    )
    if result.diagnostics != recalculated:
        raise _invalid("stored diagnostics do not match aligned content", "DIAGNOSTICS_MISMATCH")


def calculate_alignment_diagnostics(
    words: Sequence[AlignedScriptWord],
    *,
    total_asr_words: int,
    unmatched_asr_words: int,
    rejected_asr_evidence: Sequence[RejectedAsrEvidence],
) -> AlignmentDiagnostics:
    total = len(words)
    denominator = total or 1
    accepted_indices = {
        index for word in words for index in word.matched_recognition_indices
    }
    rejected_indices = {item.recognition_index for item in rejected_asr_evidence}
    classified = len(accepted_indices) + unmatched_asr_words + len(rejected_indices)
    split_groups = {
        word.alignment_operation_id
        for word in words
        if word.match_type
        in (
            AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR,
            AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR,
        )
    }
    substitution_groups = {
        item.attempted_operation_id
        for item in rejected_asr_evidence
        if item.attempted_match_type is AlignmentMatchType.SUBSTITUTION
    }
    observed = sum(word.timing_status is TimingStatus.OBSERVED for word in words)
    unresolved = sum(word.timing_status is TimingStatus.UNRESOLVED for word in words)
    text_matched = sum(word.match_type in _ACCEPTED_TYPES for word in words)
    return AlignmentDiagnostics(
        total_script_words=total,
        total_asr_words=total_asr_words,
        exact_matches=sum(word.match_type is AlignmentMatchType.EXACT for word in words),
        normalized_matches=sum(
            word.match_type is AlignmentMatchType.NORMALIZED for word in words
        ),
        fuzzy_matches=sum(word.match_type is AlignmentMatchType.FUZZY for word in words),
        split_merge_matches=len(split_groups),
        substitutions=len(substitution_groups),
        interpolated_words=sum(
            word.timing_status is TimingStatus.INTERPOLATED for word in words
        ),
        unresolved_script_words=unresolved,
        unmatched_asr_words=unmatched_asr_words,
        rejected_asr_evidence_count=len(rejected_indices),
        classified_asr_words=classified,
        provenance_complete=classified == total_asr_words,
        observed_timing_coverage=Fraction(observed, denominator),
        total_timing_coverage=Fraction(total - unresolved, denominator),
        text_alignment_coverage=Fraction(text_matched, denominator),
    )


def _validate_script(result: AlignmentResult) -> None:
    script = result.script
    if not script.exact_text:
        raise _invalid("script exact_text must not be empty", "EMPTY_SCRIPT")
    if script.exact_text.isspace():
        raise _invalid("script must contain a word", "WHITESPACE_ONLY_SCRIPT")
    if script.exact_text.startswith("\ufeff"):
        raise _invalid("decoded exact_text must not contain the UTF-8 BOM", "BOM_IN_EXACT_TEXT")
    if script.character_count != len(script.exact_text):
        raise _invalid("script character_count is incorrect", "SCRIPT_CHARACTER_COUNT_MISMATCH")
    if script.line_count != count_script_lines(script.exact_text):
        raise _invalid("script line_count is incorrect", "SCRIPT_LINE_COUNT_MISMATCH")
    if not _SHA256.fullmatch(script.source_sha256):
        raise _invalid("script SHA-256 format is invalid", "SCRIPT_SHA256_INVALID")
    raw = script.exact_text.encode("utf-8")
    if script.has_bom:
        raw = codecs.BOM_UTF8 + raw
    if hashlib.sha256(raw).hexdigest() != script.source_sha256:
        raise _invalid("script SHA-256 does not match exact text/BOM", "SCRIPT_SHA256_MISMATCH")
    expected_tokens = tokenize_script(script.exact_text)
    if not expected_tokens or not any(token.kind.value == "word" for token in expected_tokens):
        raise _invalid("script contains no word token", "SCRIPT_HAS_NO_WORDS")
    if result.tokens != expected_tokens:
        raise _invalid("tokens are not the canonical reversible tokenization", "TOKENS_MISMATCH")


def _validate_timelines(result: AlignmentResult) -> None:
    recognition = result.recognition
    edit_map = result.edit_map
    if result.sample_rate != recognition.sample_rate or result.sample_rate != edit_map.sample_rate:
        raise _invalid("alignment, recognition, and edit-map sample rates differ", "SAMPLE_RATE_MISMATCH")
    if recognition.duration_samples_cleaned != edit_map.output_total_samples:
        raise _invalid("cleaned sample totals differ", "CLEANED_DURATION_MISMATCH")
    if recognition.duration_samples_original != edit_map.source_total_samples:
        raise _invalid("original sample totals differ", "ORIGINAL_DURATION_MISMATCH")
    if not edit_map.output_sha256:
        raise _invalid("edit map has no cleaned-audio hash", "EDIT_MAP_MISSING_CLEANED_HASH")
    metadata = dict(recognition.metadata)
    for key in ("cleaned_audio_sha256", "edit_map_output_sha256"):
        if key in metadata and metadata[key] != edit_map.output_sha256:
            raise _invalid(f"recognition {key} differs from edit map", "CLEANED_AUDIO_HASH_MISMATCH")
    mapper = TimelineMapper(edit_map)
    previous_cleaned_end = -1
    previous_original_end = -1
    for index, observation in enumerate(recognition.words):
        if (
            observation.start_sample_cleaned < previous_cleaned_end
            or observation.start_sample_original < previous_original_end
        ):
            raise _invalid(f"recognition word {index} overlaps", "RECOGNITION_TIMELINE_OVERLAP")
        if (
            mapper.target_to_source(observation.start_sample_cleaned)
            != observation.start_sample_original
            or mapper.target_to_source(observation.end_sample_cleaned)
            != observation.end_sample_original
        ):
            raise _invalid(f"recognition word {index} does not map through edit map", "RECOGNITION_TIMELINE_MISMATCH")
        previous_cleaned_end = observation.end_sample_cleaned
        previous_original_end = observation.end_sample_original


def _validate_aligned_words(
    result: AlignmentResult, settings: AlignmentSettings
) -> None:
    mapper = TimelineMapper(result.edit_map)
    operation_words: dict[str, list[AlignedScriptWord]] = defaultdict(list)
    previous_cleaned_end = -1
    previous_original_end = -1
    for word in result.aligned_words:
        if word.cleaned_start_sample is not None:
            if word.cleaned_end_sample is None or word.original_start_sample is None or word.original_end_sample is None:
                raise _invalid("resolved word has incomplete boundaries", "INCOMPLETE_WORD_TIMING")
            if word.cleaned_end_sample > result.edit_map.output_total_samples:
                raise _invalid("cleaned word boundary is out of range", "CLEANED_WORD_OUT_OF_RANGE")
            if word.original_end_sample > result.edit_map.source_total_samples:
                raise _invalid("original word boundary is out of range", "ORIGINAL_WORD_OUT_OF_RANGE")
            if word.cleaned_start_sample < previous_cleaned_end or word.original_start_sample < previous_original_end:
                raise _invalid("resolved word timings overlap", "ALIGNED_WORD_OVERLAP")
            if (
                mapper.target_to_source(word.cleaned_start_sample) != word.original_start_sample
                or mapper.target_to_source(word.cleaned_end_sample) != word.original_end_sample
            ):
                raise _invalid("word timelines do not map through edit map", "WORD_TIMELINE_MISMATCH")
            previous_cleaned_end = word.cleaned_end_sample
            previous_original_end = word.original_end_sample

        if word.match_type in _ACCEPTED_TYPES:
            if not word.matched_recognition_indices or word.alignment_operation_id is None:
                raise _invalid("accepted match lacks ASR evidence/operation id", "ACCEPTED_MATCH_PROVENANCE_MISSING")
            if not _OPERATION_ID.fullmatch(word.alignment_operation_id):
                raise _invalid("accepted operation id format is invalid", "OPERATION_ID_INVALID")
            operation_words[word.alignment_operation_id].append(word)
        elif word.matched_recognition_indices:
            raise _invalid("non-accepted word claims matched ASR evidence", "NON_ACCEPTED_MATCH_HAS_ASR")

        indices = word.matched_recognition_indices
        if word.match_type in (
            AlignmentMatchType.EXACT,
            AlignmentMatchType.NORMALIZED,
            AlignmentMatchType.FUZZY,
        ):
            if word.timing_status is not TimingStatus.OBSERVED or len(indices) != 1:
                raise _invalid("1:1 match provenance is invalid", "ONE_TO_ONE_PROVENANCE_INVALID")
            _validate_one_to_one_text(result, word, indices[0], settings)
            _validate_observed_interval(result, word, indices)
        elif word.match_type is AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR:
            if word.timing_status is not TimingStatus.OBSERVED or len(indices) < 2:
                raise _invalid("one-to-many provenance is invalid", "ONE_TO_MANY_PROVENANCE_INVALID")
            if indices != tuple(range(indices[0], indices[-1] + 1)):
                raise _invalid("one-to-many ASR indices must be consecutive", "ONE_TO_MANY_NOT_CONSECUTIVE")
            _validate_one_to_many_text(result, word)
            _validate_observed_interval(result, word, indices)
        elif word.match_type is AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR:
            if word.timing_status is not TimingStatus.DISTRIBUTED or len(indices) != 1:
                raise _invalid("many-to-one provenance is invalid", "MANY_TO_ONE_PROVENANCE_INVALID")
        elif word.match_type is AlignmentMatchType.INTERPOLATED:
            _validate_interpolation(result, word)
        elif word.match_type not in (
            AlignmentMatchType.UNRESOLVED,
            AlignmentMatchType.SUBSTITUTION,
        ):
            raise _invalid("unsupported match/timing combination", "MATCH_TIMING_INCOMPATIBLE")

        expected_confidence = _combined_confidence(result, indices)
        if word.asr_confidence != expected_confidence:
            raise _invalid("ASR confidence does not match accepted evidence", "ASR_CONFIDENCE_MISMATCH")

    _validate_operation_groups(result, operation_words)
    _validate_interpolation_groups(result, settings)


def _validate_one_to_one_text(
    result: AlignmentResult,
    word: AlignedScriptWord,
    index: int,
    settings: AlignmentSettings,
) -> None:
    observation = result.recognition.words[index]
    surface_equal = word.exact_text == observation.text.strip()
    keys_equal = comparison_key(word.exact_text) == comparison_key(observation.text)
    if word.match_type is AlignmentMatchType.EXACT and not surface_equal:
        raise _invalid("exact match surfaces differ", "EXACT_TEXT_EVIDENCE_MISMATCH")
    if word.match_type is AlignmentMatchType.NORMALIZED and (surface_equal or not keys_equal):
        raise _invalid("normalized match evidence is inconsistent", "NORMALIZED_TEXT_EVIDENCE_MISMATCH")
    if word.match_type is AlignmentMatchType.FUZZY:
        similarity = string_similarity(
            comparison_key(word.exact_text), comparison_key(observation.text)
        )
        if (
            keys_equal
            or word.text_similarity != similarity
            or min(
                len(comparison_key(word.exact_text)),
                len(comparison_key(observation.text)),
            )
            < settings.min_fuzzy_token_length
            or similarity < Fraction(settings.fuzzy_threshold)
        ):
            raise _invalid("fuzzy similarity is inconsistent", "FUZZY_TEXT_EVIDENCE_MISMATCH")


def _validate_one_to_many_text(result: AlignmentResult, word: AlignedScriptWord) -> None:
    script_key = structural_key((comparison_key(word.exact_text),))
    asr_key = structural_key(
        tuple(comparison_key(result.recognition.words[index].text) for index in word.matched_recognition_indices)
    )
    if not script_key or script_key != asr_key:
        raise _invalid("one-to-many structural keys differ", "ONE_TO_MANY_TEXT_MISMATCH")


def _validate_observed_interval(
    result: AlignmentResult, word: AlignedScriptWord, indices: tuple[int, ...]
) -> None:
    first = result.recognition.words[indices[0]]
    last = result.recognition.words[indices[-1]]
    if (
        word.cleaned_start_sample != first.start_sample_cleaned
        or word.cleaned_end_sample != last.end_sample_cleaned
    ):
        raise _invalid("observed word interval differs from ASR evidence", "OBSERVED_INTERVAL_MISMATCH")


def _validate_operation_groups(
    result: AlignmentResult, operation_words: dict[str, list[AlignedScriptWord]]
) -> None:
    accepted_index_owner: dict[int, str] = {}
    for operation_id, words in sorted(operation_words.items()):
        match_types = {word.match_type for word in words}
        if len(match_types) != 1:
            raise _invalid("operation mixes match types", "OPERATION_MATCH_TYPE_CONFLICT")
        match_type = next(iter(match_types))
        if match_type is AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR:
            if len(words) < 2 or [word.script_word_index for word in words] != list(
                range(words[0].script_word_index, words[-1].script_word_index + 1)
            ):
                raise _invalid("many-to-one script group is not consecutive", "MANY_TO_ONE_GROUP_INVALID")
            indices = {word.matched_recognition_indices for word in words}
            if len(indices) != 1:
                raise _invalid("many-to-one group does not share one ASR index", "MANY_TO_ONE_INDEX_CONFLICT")
            recognition_index = words[0].matched_recognition_indices[0]
            observation = result.recognition.words[recognition_index]
            if words[0].cleaned_start_sample != observation.start_sample_cleaned or words[-1].cleaned_end_sample != observation.end_sample_cleaned:
                raise _invalid("many-to-one group does not cover ASR interval", "MANY_TO_ONE_RANGE_MISMATCH")
            for left, right in zip(words, words[1:]):
                if left.cleaned_end_sample != right.cleaned_start_sample:
                    raise _invalid("many-to-one partitions are not adjacent", "MANY_TO_ONE_PARTITION_GAP")
            expected_ranges = _allocate_ranges(
                observation.start_sample_cleaned,
                observation.end_sample_cleaned,
                tuple(max(1, len(comparison_key(word.exact_text))) for word in words),
            )
            actual_ranges = tuple(
                (word.cleaned_start_sample, word.cleaned_end_sample) for word in words
            )
            if expected_ranges is None or actual_ranges != expected_ranges:
                raise _invalid("many-to-one partition is not deterministic", "MANY_TO_ONE_PARTITION_MISMATCH")
            script_key = structural_key(tuple(comparison_key(word.exact_text) for word in words))
            if not script_key or script_key != structural_key((comparison_key(observation.text),)):
                raise _invalid("many-to-one structural keys differ", "MANY_TO_ONE_TEXT_MISMATCH")
        elif len(words) != 1:
            raise _invalid("accepted operation id is reused", "OPERATION_ID_REUSED")

        for word in words:
            for recognition_index in word.matched_recognition_indices:
                owner = accepted_index_owner.setdefault(recognition_index, operation_id)
                if owner != operation_id:
                    raise _invalid("ASR index is accepted by multiple operations", "ACCEPTED_INDEX_REUSED")


def _validate_interpolation(result: AlignmentResult, word: AlignedScriptWord) -> None:
    left_index = word.interpolation_left_anchor_script_word_index
    right_index = word.interpolation_right_anchor_script_word_index
    if left_index is None or right_index is None:
        raise _invalid("interpolated word lacks anchors", "INTERPOLATION_ANCHORS_MISSING")
    if not left_index < word.script_word_index < right_index:
        raise _invalid("interpolation anchors are not around the word", "INTERPOLATION_ANCHOR_ORDER_INVALID")
    if right_index >= len(result.aligned_words):
        raise _invalid("interpolation anchor is out of range", "INTERPOLATION_ANCHOR_OUT_OF_RANGE")
    left = result.aligned_words[left_index]
    right = result.aligned_words[right_index]
    if left.match_type not in _ANCHOR_TYPES or right.match_type not in _ANCHOR_TYPES:
        raise _invalid("interpolation anchor is not reliable", "INTERPOLATION_ANCHOR_UNRELIABLE")
    if left.cleaned_end_sample is None or right.cleaned_start_sample is None:
        raise _invalid("interpolation anchor has no timing", "INTERPOLATION_ANCHOR_UNTIMED")
    if word.cleaned_start_sample is None or word.cleaned_end_sample is None:
        raise _invalid("interpolated word has no interval", "INTERPOLATION_TIMING_MISSING")
    if word.cleaned_start_sample < left.cleaned_end_sample or word.cleaned_end_sample > right.cleaned_start_sample:
        raise _invalid("interpolated word is outside anchor gap", "INTERPOLATION_OUTSIDE_ANCHORS")


def _validate_interpolation_groups(
    result: AlignmentResult, settings: AlignmentSettings
) -> None:
    groups: dict[tuple[int, int], list[AlignedScriptWord]] = defaultdict(list)
    for word in result.aligned_words:
        if word.timing_status is TimingStatus.INTERPOLATED:
            assert word.interpolation_left_anchor_script_word_index is not None
            assert word.interpolation_right_anchor_script_word_index is not None
            groups[(word.interpolation_left_anchor_script_word_index, word.interpolation_right_anchor_script_word_index)].append(word)
    for (left_index, right_index), words in groups.items():
        left = result.aligned_words[left_index]
        right = result.aligned_words[right_index]
        if [word.script_word_index for word in words] != list(range(left_index + 1, right_index)):
            raise _invalid("interpolated group does not cover script gap", "INTERPOLATION_GROUP_INCOMPLETE")
        if words[0].cleaned_start_sample != left.cleaned_end_sample or words[-1].cleaned_end_sample != right.cleaned_start_sample:
            raise _invalid("interpolated group does not cover timing gap", "INTERPOLATION_RANGE_INCOMPLETE")
        for first, second in zip(words, words[1:]):
            if first.cleaned_end_sample != second.cleaned_start_sample:
                raise _invalid("interpolated partitions are not adjacent", "INTERPOLATION_PARTITION_GAP")
        if len(words) > settings.max_interpolation_words:
            raise _invalid("interpolation exceeds configured word limit", "INTERPOLATION_WORD_LIMIT_EXCEEDED")
        if left.cleaned_end_sample is None or right.cleaned_start_sample is None:
            raise _invalid("interpolation anchors are untimed", "INTERPOLATION_ANCHOR_UNTIMED")
        gap = right.cleaned_start_sample - left.cleaned_end_sample
        if gap * 1_000 > settings.max_interpolation_gap_ms * result.sample_rate:
            raise _invalid("interpolation exceeds configured gap limit", "INTERPOLATION_GAP_LIMIT_EXCEEDED")
        expected_ranges = _allocate_ranges(
            left.cleaned_end_sample,
            right.cleaned_start_sample,
            tuple(max(1, len(comparison_key(word.exact_text))) for word in words),
        )
        actual_ranges = tuple(
            (word.cleaned_start_sample, word.cleaned_end_sample) for word in words
        )
        if expected_ranges is None or actual_ranges != expected_ranges:
            raise _invalid("interpolation partition is not deterministic", "INTERPOLATION_PARTITION_MISMATCH")


def _validate_provenance(result: AlignmentResult) -> None:
    total = len(result.recognition.words)
    accepted = {index for word in result.aligned_words for index in word.matched_recognition_indices}
    unmatched = tuple(word.recognition_index for word in result.unmatched_asr_words)
    rejected = tuple(item.recognition_index for item in result.rejected_asr_evidence)
    if unmatched != tuple(sorted(set(unmatched))) or rejected != tuple(sorted(set(rejected))):
        raise _invalid("diagnostic ASR indices must be unique and sorted", "PROVENANCE_ORDER_INVALID")
    unmatched_set = set(unmatched)
    rejected_set = set(rejected)
    if accepted & unmatched_set or accepted & rejected_set or unmatched_set & rejected_set:
        raise _invalid("ASR provenance categories overlap", "PROVENANCE_CATEGORY_OVERLAP")
    known = set(range(total))
    classified = accepted | unmatched_set | rejected_set
    if classified != known:
        raise _invalid("ASR provenance is incomplete or contains unknown indices", "PROVENANCE_INCOMPLETE")
    mapper = TimelineMapper(result.edit_map)
    for item in result.unmatched_asr_words:
        _validate_evidence_copy(result, item, mapper)
    for item in result.rejected_asr_evidence:
        _validate_evidence_copy(result, item, mapper)
        if any(index >= len(result.aligned_words) for index in item.related_script_word_indices):
            raise _invalid("rejected evidence references unknown script word", "REJECTED_SCRIPT_INDEX_UNKNOWN")
        if not _OPERATION_ID.fullmatch(item.attempted_operation_id):
            raise _invalid("rejected operation id format is invalid", "REJECTED_OPERATION_ID_INVALID")
        if item.attempted_match_type is AlignmentMatchType.SUBSTITUTION:
            if item.rejection_reason != "substitution_not_accepted":
                raise _invalid("substitution rejection reason is invalid", "REJECTION_REASON_INVALID")
        elif item.attempted_match_type is AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR:
            if item.rejection_reason != "timing_distribution_impossible":
                raise _invalid("split/merge rejection reason is invalid", "REJECTION_REASON_INVALID")
        else:
            raise _invalid("unsupported rejected evidence type", "REJECTED_MATCH_TYPE_INVALID")
    substitution_word_indices = {
        word.script_word_index
        for word in result.aligned_words
        if word.match_type is AlignmentMatchType.SUBSTITUTION
    }
    rejected_substitution_indices = {
        index
        for item in result.rejected_asr_evidence
        if item.attempted_match_type is AlignmentMatchType.SUBSTITUTION
        for index in item.related_script_word_indices
    }
    if substitution_word_indices - rejected_substitution_indices:
        raise _invalid("substitution word has no rejected ASR evidence", "SUBSTITUTION_EVIDENCE_MISSING")


def _validate_evidence_copy(result: AlignmentResult, item: object, mapper: TimelineMapper) -> None:
    index = getattr(item, "recognition_index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(result.recognition.words):
        raise _invalid("ASR evidence index is out of range", "ASR_EVIDENCE_INDEX_INVALID")
    observation = result.recognition.words[index]
    for name, expected in (
        ("text", observation.text),
        ("cleaned_start_sample", observation.start_sample_cleaned),
        ("cleaned_end_sample", observation.end_sample_cleaned),
        ("original_start_sample", observation.start_sample_original),
        ("original_end_sample", observation.end_sample_original),
        ("confidence", observation.confidence),
    ):
        if getattr(item, name) != expected:
            raise _invalid("ASR evidence copy differs from recognition observation", "ASR_EVIDENCE_MISMATCH")
    if (
        mapper.target_to_source(item.cleaned_start_sample) != item.original_start_sample
        or mapper.target_to_source(item.cleaned_end_sample) != item.original_end_sample
    ):
        raise _invalid("ASR evidence timelines do not map", "ASR_EVIDENCE_TIMELINE_MISMATCH")


def _combined_confidence(result: AlignmentResult, indices: tuple[int, ...]) -> float | None:
    if not indices:
        return None
    values = tuple(result.recognition.words[index].confidence for index in indices)
    if any(value is None for value in values):
        return None
    return min(value for value in values if value is not None)


def _settings_from_snapshot(result: AlignmentResult) -> AlignmentSettings:
    snapshot = dict(result.configuration_snapshot)
    expected_keys = {
        "enable_fuzzy_matching",
        "enable_split_merge",
        "fuzzy_threshold",
        "max_dp_cells",
        "max_interpolation_gap_ms",
        "max_interpolation_words",
        "min_fuzzy_token_length",
        "minimum_coverage_warning",
        "policy_version",
    }
    if set(snapshot) != expected_keys or snapshot.get("policy_version") != "script-asr-dp-v1":
        raise _invalid("alignment configuration snapshot is incomplete", "CONFIGURATION_SNAPSHOT_INVALID")
    try:
        return AlignmentSettings(
            fuzzy_threshold=Decimal(snapshot["fuzzy_threshold"]),
            min_fuzzy_token_length=int(snapshot["min_fuzzy_token_length"]),
            max_dp_cells=int(snapshot["max_dp_cells"]),
            max_interpolation_words=int(snapshot["max_interpolation_words"]),
            max_interpolation_gap_ms=int(snapshot["max_interpolation_gap_ms"]),
            minimum_coverage_warning=Decimal(snapshot["minimum_coverage_warning"]),
            enable_split_merge=_snapshot_boolean(snapshot["enable_split_merge"]),
            enable_fuzzy_matching=_snapshot_boolean(
                snapshot["enable_fuzzy_matching"]
            ),
        )
    except (InvalidOperation, ValueError, TypeError, ConfigurationError) as exc:
        raise _invalid("alignment configuration snapshot is invalid", "CONFIGURATION_SNAPSHOT_INVALID") from exc


def _snapshot_boolean(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("boolean snapshot value must be true or false")


def _allocate_ranges(
    start: int, end: int, weights: tuple[int, ...]
) -> tuple[tuple[int, int], ...] | None:
    total = end - start
    if not weights or total < len(weights):
        return None
    remaining = total - len(weights)
    weight_total = sum(weights)
    lengths = [1 + (remaining * weight // weight_total) for weight in weights]
    leftover = total - sum(lengths)
    for index in range(leftover):
        lengths[index] += 1
    cursor = start
    ranges: list[tuple[int, int]] = []
    for length in lengths:
        ranges.append((cursor, cursor + length))
        cursor += length
    return tuple(ranges)


def _invalid(message: str, code: str) -> AlignmentValidationError:
    return AlignmentValidationError(message, code=code)
