"""Script-preserving alignment orchestration, timing assignment, and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.alignment.engine import (
    AlignmentOperation,
    ScriptAsrAlignmentEngine,
)
from larp_audio_mvp.alignment.script import read_script
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.alignment.validation import (
    ALIGNMENT_SCHEMA_VERSION,
    calculate_alignment_diagnostics,
    validate_alignment_result,
)
from larp_audio_mvp.audio.serialization import read_edit_map
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import (
    AlignedScriptWord,
    AlignmentDiagnostics,
    AlignmentMatchType,
    AlignmentResult,
    EditMap,
    RejectedAsrEvidence,
    RecognitionResult,
    RecognizedWord,
    ScriptDocument,
    ScriptToken,
    ScriptTokenKind,
    TimingStatus,
    UnmatchedAsrWord,
)
from larp_audio_mvp.core.errors import AlignmentValidationError
from larp_audio_mvp.core.timeline import TimelineMapper
from larp_audio_mvp.models.serialization import read_recognition

@dataclass(slots=True)
class _AssignedWord:
    token: ScriptToken
    match_type: AlignmentMatchType = AlignmentMatchType.UNRESOLVED
    timing_status: TimingStatus = TimingStatus.UNRESOLVED
    recognition_indices: tuple[int, ...] = ()
    operation_id: str | None = None
    interpolation_left_anchor: int | None = None
    interpolation_right_anchor: int | None = None
    similarity: Fraction | None = None
    alignment_score: Fraction | None = None
    confidence: float | None = None
    cleaned_start: int | None = None
    cleaned_end: int | None = None
    warnings: tuple[str, ...] = ()


class ScriptAlignmentService:
    """Align exact script word spans to existing local ASR observations."""

    def __init__(self, settings: AlignmentSettings) -> None:
        self._settings = settings
        self._engine = ScriptAsrAlignmentEngine(settings)

    def align(
        self,
        script: ScriptDocument,
        recognition: RecognitionResult,
        edit_map: EditMap,
    ) -> AlignmentResult:
        _validate_compatibility(recognition, edit_map)
        tokens = tokenize_script(script.exact_text)
        script_words = tuple(
            token for token in tokens if token.kind is ScriptTokenKind.WORD
        )
        if not script_words:
            raise AlignmentValidationError(
                "script contains no word tokens", code="SCRIPT_HAS_NO_WORDS"
            )
        operations = self._engine.align(script_words, recognition.words)
        mapper = TimelineMapper(edit_map)
        assigned, unmatched, rejected = _assign_observed_timings(
            script_words, recognition.words, operations
        )
        _interpolate(assigned, recognition.sample_rate, self._settings)
        aligned_words = _finalize_words(assigned, mapper)
        unmatched_words = tuple(
            _unmatched_word(index, recognition.words[index], mapper)
            for index in sorted(unmatched)
        )
        rejected_evidence = tuple(sorted(rejected, key=lambda item: item.recognition_index))
        diagnostics = calculate_alignment_diagnostics(
            aligned_words,
            total_asr_words=len(recognition.words),
            unmatched_asr_words=len(unmatched_words),
            rejected_asr_evidence=rejected_evidence,
        )
        warnings = _result_warnings(diagnostics, self._settings)
        result = AlignmentResult(
            schema_version=ALIGNMENT_SCHEMA_VERSION,
            script=script,
            recognition=recognition,
            edit_map=edit_map,
            sample_rate=recognition.sample_rate,
            tokens=tokens,
            aligned_words=aligned_words,
            unmatched_asr_words=unmatched_words,
            rejected_asr_evidence=rejected_evidence,
            diagnostics=diagnostics,
            configuration_snapshot=self._settings.snapshot(),
            warnings=warnings,
        )
        validate_alignment_result(result)
        return result


def align_files(
    *,
    script_path: Path,
    recognition_path: Path,
    edit_map_path: Path,
    settings: AlignmentSettings,
) -> AlignmentResult:
    """Load strict Stage 6/7 artifacts, validate their identity, and align."""

    script = read_script(script_path)
    recognition = read_recognition(recognition_path)
    edit_map = read_edit_map(edit_map_path)
    metadata = dict(recognition.metadata)
    expected_map_output_hash = metadata.get("edit_map_output_sha256")
    if (
        expected_map_output_hash is not None
        and expected_map_output_hash != edit_map.output_sha256
    ):
        raise AlignmentValidationError(
            "recognition metadata does not match edit-map cleaned-audio hash",
            code="EDIT_MAP_OUTPUT_HASH_MISMATCH",
        )
    return ScriptAlignmentService(settings).align(script, recognition, edit_map)


def _validate_compatibility(
    recognition: RecognitionResult, edit_map: EditMap
) -> None:
    if recognition.schema_version != "1":
        raise AlignmentValidationError(
            "unsupported recognition schema version",
            code="RECOGNITION_SCHEMA_MISMATCH",
        )
    if edit_map.schema_version != "1":
        raise AlignmentValidationError(
            "unsupported edit map schema version", code="EDIT_MAP_SCHEMA_MISMATCH"
        )
    if recognition.sample_rate != edit_map.sample_rate:
        raise AlignmentValidationError(
            "recognition and edit map sample rates differ",
            code="SAMPLE_RATE_MISMATCH",
        )
    if recognition.duration_samples_cleaned != edit_map.output_total_samples:
        raise AlignmentValidationError(
            "recognition cleaned duration differs from edit map",
            code="CLEANED_DURATION_MISMATCH",
        )
    if recognition.duration_samples_original != edit_map.source_total_samples:
        raise AlignmentValidationError(
            "recognition original duration differs from edit map",
            code="ORIGINAL_DURATION_MISMATCH",
        )
    if not edit_map.output_sha256:
        raise AlignmentValidationError(
            "edit map has no cleaned-audio SHA-256",
            code="EDIT_MAP_MISSING_CLEANED_HASH",
        )
    cleaned_hash = dict(recognition.metadata).get("cleaned_audio_sha256")
    if cleaned_hash is not None and cleaned_hash != edit_map.output_sha256:
        raise AlignmentValidationError(
            "recognition cleaned-audio hash differs from edit map",
            code="CLEANED_AUDIO_HASH_MISMATCH",
        )
    mapper = TimelineMapper(edit_map)
    previous_cleaned_end = -1
    previous_original_end = -1
    for index, word in enumerate(recognition.words):
        if (
            word.start_sample_cleaned < previous_cleaned_end
            or word.start_sample_original < previous_original_end
        ):
            raise AlignmentValidationError(
                f"recognition word {index} overlaps its predecessor",
                code="RECOGNITION_TIMELINE_OVERLAP",
            )
        if (
            mapper.target_to_source(word.start_sample_cleaned)
            != word.start_sample_original
            or mapper.target_to_source(word.end_sample_cleaned)
            != word.end_sample_original
        ):
            raise AlignmentValidationError(
                f"recognition word {index} has incompatible original timing",
                code="RECOGNITION_TIMELINE_MISMATCH",
            )
        previous_cleaned_end = word.end_sample_cleaned
        previous_original_end = word.end_sample_original


def _assign_observed_timings(
    script_words: Sequence[ScriptToken],
    recognition_words: Sequence[RecognizedWord],
    operations: Sequence[AlignmentOperation],
) -> tuple[list[_AssignedWord], set[int], list[RejectedAsrEvidence]]:
    assigned = [_AssignedWord(token=token) for token in script_words]
    unmatched: set[int] = set()
    rejected: list[RejectedAsrEvidence] = []
    for operation_number, operation in enumerate(operations):
        operation_id = f"alignment-op-{operation_number:06d}"
        if not operation.script_indices:
            unmatched.update(operation.recognition_indices)
            continue
        if operation.match_type is AlignmentMatchType.UNRESOLVED:
            script_index = operation.script_indices[0]
            assigned[script_index] = _AssignedWord(
                token=script_words[script_index],
                match_type=operation.match_type,
                warnings=("no reliable observed timing assigned",),
            )
            continue
        if operation.match_type is AlignmentMatchType.SUBSTITUTION:
            script_index = operation.script_indices[0]
            assigned[script_index] = _AssignedWord(
                token=script_words[script_index],
                match_type=operation.match_type,
                warnings=("substitution evidence was not accepted as a match",),
            )
            rejected.extend(
                _rejected_evidence(
                    recognition_index=index,
                    word=recognition_words[index],
                    reason="substitution_not_accepted",
                    script_indices=operation.script_indices,
                    attempted_match_type=operation.match_type,
                    operation_id=operation_id,
                )
                for index in operation.recognition_indices
            )
            continue

        if operation.match_type is AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR:
            asr = recognition_words[operation.recognition_indices[0]]
            weights = tuple(
                max(1, len(script_words[index].comparison_key or ""))
                for index in operation.script_indices
            )
            ranges = _allocate_ranges(
                asr.start_sample_cleaned, asr.end_sample_cleaned, weights
            )
            if ranges is None:
                for script_index in operation.script_indices:
                    assigned[script_index] = _AssignedWord(
                        token=script_words[script_index],
                        warnings=(
                            "many-to-one timing distribution was rejected because "
                            "the ASR interval is too short",
                        ),
                    )
                rejected.append(
                    _rejected_evidence(
                        recognition_index=operation.recognition_indices[0],
                        word=asr,
                        reason="timing_distribution_impossible",
                        script_indices=operation.script_indices,
                        attempted_match_type=operation.match_type,
                        operation_id=operation_id,
                    )
                )
                continue
            for script_index, (start, end) in zip(operation.script_indices, ranges):
                assigned[script_index] = _AssignedWord(
                    token=script_words[script_index],
                    match_type=operation.match_type,
                    timing_status=TimingStatus.DISTRIBUTED,
                    recognition_indices=operation.recognition_indices,
                    operation_id=operation_id,
                    similarity=operation.similarity,
                    alignment_score=Fraction(4, 5),
                    confidence=asr.confidence,
                    cleaned_start=start,
                    cleaned_end=end,
                )
            continue

        asr_words = tuple(
            recognition_words[index] for index in operation.recognition_indices
        )
        start = asr_words[0].start_sample_cleaned
        end = asr_words[-1].end_sample_cleaned
        score = {
            AlignmentMatchType.EXACT: Fraction(1),
            AlignmentMatchType.NORMALIZED: Fraction(9, 10),
            AlignmentMatchType.FUZZY: operation.similarity or Fraction(0),
            AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR: Fraction(4, 5),
        }[operation.match_type]
        script_index = operation.script_indices[0]
        assigned[script_index] = _AssignedWord(
            token=script_words[script_index],
            match_type=operation.match_type,
            timing_status=TimingStatus.OBSERVED,
            recognition_indices=operation.recognition_indices,
            operation_id=operation_id,
            similarity=operation.similarity,
            alignment_score=score,
            confidence=_combined_confidence(
                recognition_words, operation.recognition_indices
            ),
            cleaned_start=start,
            cleaned_end=end,
        )
    return assigned, unmatched, rejected


def _interpolate(
    assigned: list[_AssignedWord],
    sample_rate: int,
    settings: AlignmentSettings,
) -> None:
    index = 0
    while index < len(assigned):
        if assigned[index].timing_status is not TimingStatus.UNRESOLVED:
            index += 1
            continue
        start = index
        while index < len(assigned) and (
            assigned[index].timing_status is TimingStatus.UNRESOLVED
        ):
            index += 1
        end = index
        if start == 0 or end == len(assigned):
            continue
        missing = end - start
        if missing > settings.max_interpolation_words:
            continue
        before = assigned[start - 1]
        after = assigned[end]
        if not _reliable_anchor(before) or not _reliable_anchor(after):
            continue
        assert before.cleaned_end is not None and after.cleaned_start is not None
        gap = after.cleaned_start - before.cleaned_end
        if gap <= 0 or gap * 1_000 > settings.max_interpolation_gap_ms * sample_rate:
            continue
        weights = tuple(
            max(1, len(assigned[position].token.comparison_key or ""))
            for position in range(start, end)
        )
        ranges = _allocate_ranges(before.cleaned_end, after.cleaned_start, weights)
        if ranges is None:
            continue
        for position, (range_start, range_end) in zip(range(start, end), ranges):
            current = assigned[position]
            assigned[position] = _AssignedWord(
                token=current.token,
                match_type=AlignmentMatchType.INTERPOLATED,
                timing_status=TimingStatus.INTERPOLATED,
                recognition_indices=(),
                operation_id=None,
                interpolation_left_anchor=start - 1,
                interpolation_right_anchor=end,
                similarity=None,
                alignment_score=None,
                confidence=None,
                cleaned_start=range_start,
                cleaned_end=range_end,
                warnings=("timing interpolated between reliable ASR anchors",),
            )


def _reliable_anchor(word: _AssignedWord) -> bool:
    return word.match_type in (
        AlignmentMatchType.EXACT,
        AlignmentMatchType.NORMALIZED,
        AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR,
        AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR,
    ) and word.timing_status in (TimingStatus.OBSERVED, TimingStatus.DISTRIBUTED)


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


def _finalize_words(
    assigned: Sequence[_AssignedWord], mapper: TimelineMapper
) -> tuple[AlignedScriptWord, ...]:
    result: list[AlignedScriptWord] = []
    previous_cleaned_end = -1
    previous_original_end = -1
    for word_index, word in enumerate(assigned):
        original_start: int | None = None
        original_end: int | None = None
        if word.cleaned_start is not None and word.cleaned_end is not None:
            if word.cleaned_start < previous_cleaned_end:
                raise AlignmentValidationError(
                    "assigned cleaned timings overlap",
                    code="ALIGNMENT_TIMING_OVERLAP",
                )
            original_start = mapper.target_to_source(word.cleaned_start)
            original_end = mapper.target_to_source(word.cleaned_end)
            if original_start < previous_original_end or original_end <= original_start:
                raise AlignmentValidationError(
                    "mapped original timings overlap or collapse",
                    code="ALIGNMENT_ORIGINAL_TIMING_INVALID",
                )
            previous_cleaned_end = word.cleaned_end
            previous_original_end = original_end
        result.append(
            AlignedScriptWord(
                script_word_index=word_index,
                token_index=word.token.token_index,
                exact_text=word.token.exact_text,
                char_start=word.token.char_start,
                char_end=word.token.char_end,
                cleaned_start_sample=word.cleaned_start,
                cleaned_end_sample=word.cleaned_end,
                original_start_sample=original_start,
                original_end_sample=original_end,
                timing_status=word.timing_status,
                match_type=word.match_type,
                matched_recognition_indices=word.recognition_indices,
                alignment_operation_id=word.operation_id,
                interpolation_left_anchor_script_word_index=(
                    word.interpolation_left_anchor
                ),
                interpolation_right_anchor_script_word_index=(
                    word.interpolation_right_anchor
                ),
                text_similarity=word.similarity,
                alignment_score=word.alignment_score,
                asr_confidence=word.confidence,
                warnings=word.warnings,
            )
        )
    return tuple(result)


def _unmatched_word(
    index: int, word: RecognizedWord, mapper: TimelineMapper
) -> UnmatchedAsrWord:
    return UnmatchedAsrWord(
        recognition_index=index,
        text=word.text,
        cleaned_start_sample=word.start_sample_cleaned,
        cleaned_end_sample=word.end_sample_cleaned,
        original_start_sample=mapper.target_to_source(word.start_sample_cleaned),
        original_end_sample=mapper.target_to_source(word.end_sample_cleaned),
        confidence=word.confidence,
    )


def _rejected_evidence(
    *,
    recognition_index: int,
    word: RecognizedWord,
    reason: str,
    script_indices: tuple[int, ...],
    attempted_match_type: AlignmentMatchType,
    operation_id: str,
) -> RejectedAsrEvidence:
    return RejectedAsrEvidence(
        recognition_index=recognition_index,
        text=word.text,
        cleaned_start_sample=word.start_sample_cleaned,
        cleaned_end_sample=word.end_sample_cleaned,
        original_start_sample=word.start_sample_original,
        original_end_sample=word.end_sample_original,
        confidence=word.confidence,
        rejection_reason=reason,
        related_script_word_indices=script_indices,
        attempted_match_type=attempted_match_type,
        attempted_operation_id=operation_id,
    )


def _combined_confidence(
    words: Sequence[RecognizedWord], indices: tuple[int, ...]
) -> float | None:
    values = tuple(words[index].confidence for index in indices)
    if not values or any(value is None for value in values):
        return None
    return min(value for value in values if value is not None)


def _result_warnings(
    diagnostics: AlignmentDiagnostics, settings: AlignmentSettings
) -> tuple[str, ...]:
    warnings: list[str] = []
    minimum = Fraction(settings.minimum_coverage_warning)
    if diagnostics.text_alignment_coverage < minimum:
        warnings.append("text alignment coverage is below configured minimum")
    if diagnostics.total_timing_coverage < minimum:
        warnings.append("timing coverage is below configured minimum")
    if diagnostics.total_script_words and (
        diagnostics.fuzzy_matches * 5 > diagnostics.total_script_words
    ):
        warnings.append("more than 20% of script words use fuzzy matching")
    if diagnostics.total_script_words and (
        diagnostics.unresolved_script_words * 5 > diagnostics.total_script_words
    ):
        warnings.append("more than 20% of script words remain unresolved")
    divergence = abs(diagnostics.total_script_words - diagnostics.total_asr_words)
    if divergence > max(3, diagnostics.total_script_words // 4):
        warnings.append("script and ASR word counts differ significantly")
    if diagnostics.unmatched_asr_words > max(2, diagnostics.total_asr_words // 5):
        warnings.append("ASR contains many unmatched insertion words")
    if diagnostics.rejected_asr_evidence_count:
        warnings.append("one or more ASR observations were rejected as match evidence")
    return tuple(warnings)
