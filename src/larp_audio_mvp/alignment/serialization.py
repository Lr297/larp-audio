"""Deterministic schema-v2 serialization with strict standalone validation."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

from larp_audio_mvp.alignment.validation import (
    ALIGNMENT_SCHEMA_VERSION,
    validate_alignment_result,
)
from larp_audio_mvp.audio.serialization import edit_map_from_dict, edit_map_to_dict
from larp_audio_mvp.core.contracts import (
    AlignedScriptWord,
    AlignmentDiagnostics,
    AlignmentMatchType,
    AlignmentResult,
    RejectedAsrEvidence,
    ScriptDocument,
    ScriptToken,
    ScriptTokenKind,
    TimingStatus,
    UnmatchedAsrWord,
)
from larp_audio_mvp.core.errors import (
    AlignmentSerializationError,
    AlignmentValidationError,
)
from larp_audio_mvp.models.serialization import (
    recognition_from_dict,
    recognition_to_dict,
)


def alignment_to_dict(result: AlignmentResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "sample_rate": result.sample_rate,
        "script": {
            "source_path": str(result.script.source_path),
            "source_sha256": result.script.source_sha256,
            "encoding": result.script.encoding,
            "has_bom": result.script.has_bom,
            "character_count": result.script.character_count,
            "line_count": result.script.line_count,
            "source_kind": result.script.source_kind,
            "newline_style": result.script.newline_style,
            "exact_text": result.script.exact_text,
        },
        "recognition": recognition_to_dict(result.recognition),
        "edit_map": edit_map_to_dict(result.edit_map),
        "tokens": [_token_to_dict(token) for token in result.tokens],
        "aligned_words": [_aligned_word_to_dict(word) for word in result.aligned_words],
        "unmatched_asr_words": [
            _unmatched_to_dict(word) for word in result.unmatched_asr_words
        ],
        "rejected_asr_evidence": [
            _rejected_to_dict(item) for item in result.rejected_asr_evidence
        ],
        "diagnostics": _diagnostics_to_dict(result.diagnostics),
        "configuration": dict(result.configuration_snapshot),
        "warnings": list(result.warnings),
    }


def write_alignment_atomic(result: AlignmentResult, destination: Path) -> None:
    validate_alignment_result(result)
    path = destination.expanduser().resolve()
    if path.suffix.lower() != ".json":
        raise AlignmentSerializationError(
            "alignment destination must use .json",
            code="ALIGNMENT_INVALID_OUTPUT_EXTENSION",
        )
    if path.exists() and path.is_dir():
        raise AlignmentSerializationError(
            "alignment destination is a directory",
            code="ALIGNMENT_OUTPUT_IS_DIRECTORY",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".partial.json", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                alignment_to_dict(result),
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except (OSError, ValueError) as exc:
        raise AlignmentSerializationError(
            f"cannot publish alignment JSON: {path.name}",
            code="ALIGNMENT_OUTPUT_PUBLISH_FAILED",
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def read_alignment(source: Path) -> AlignmentResult:
    path = source.expanduser().resolve()
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            payload = json.load(stream, parse_constant=_reject_json_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise AlignmentSerializationError(
            f"cannot read alignment JSON: {path.name}",
            code="ALIGNMENT_READ_FAILED",
        ) from exc
    return alignment_from_dict(payload)


def alignment_from_dict(payload: Any) -> AlignmentResult:
    """Deserialize v2 and convert every malformed-input failure to a project error."""

    try:
        root = _mapping(payload, "alignment")
        schema_version = _string(root, "schema_version")
        if schema_version != ALIGNMENT_SCHEMA_VERSION:
            raise AlignmentSerializationError(
                f"unsupported alignment schema_version: {schema_version}",
                code="UNSUPPORTED_ALIGNMENT_SCHEMA",
            )
        script = _mapping(root.get("script"), "script")
        diagnostics = _mapping(root.get("diagnostics"), "diagnostics")
        result = AlignmentResult(
            schema_version=schema_version,
            sample_rate=_integer(root, "sample_rate"),
            script=ScriptDocument(
                exact_text=_string(script, "exact_text", allow_empty=True),
                source_path=Path(_string(script, "source_path")),
                source_sha256=_string(script, "source_sha256"),
                encoding=_string(script, "encoding"),
                has_bom=_boolean(script, "has_bom"),
                character_count=_integer(script, "character_count"),
                line_count=_integer(script, "line_count"),
                source_kind=_optional_string(script, "source_kind"),
                newline_style=_optional_string(script, "newline_style"),
            ),
            recognition=recognition_from_dict(root.get("recognition")),
            edit_map=edit_map_from_dict(root.get("edit_map")),
            tokens=tuple(_token_from_dict(item) for item in _array(root, "tokens")),
            aligned_words=tuple(
                _aligned_word_from_dict(item) for item in _array(root, "aligned_words")
            ),
            unmatched_asr_words=tuple(
                _unmatched_from_dict(item)
                for item in _array(root, "unmatched_asr_words")
            ),
            rejected_asr_evidence=tuple(
                _rejected_from_dict(item)
                for item in _array(root, "rejected_asr_evidence")
            ),
            diagnostics=_diagnostics_from_dict(diagnostics),
            configuration_snapshot=tuple(
                sorted(
                    _string_mapping(root.get("configuration"), "configuration").items()
                )
            ),
            warnings=_string_array(root, "warnings"),
        )
        validate_alignment_result(result)
        return result
    except (AlignmentSerializationError, AlignmentValidationError):
        raise
    except Exception as exc:
        raise AlignmentSerializationError(
            "alignment JSON does not satisfy alignment.schema.v2",
            code="INVALID_ALIGNMENT_JSON",
        ) from exc


def _token_to_dict(token: ScriptToken) -> dict[str, Any]:
    return {
        "token_index": token.token_index,
        "kind": token.kind.value,
        "exact_text": token.exact_text,
        "char_start": token.char_start,
        "char_end": token.char_end,
        "comparison_key": token.comparison_key,
    }


def _aligned_word_to_dict(word: AlignedScriptWord) -> dict[str, Any]:
    return {
        "script_word_index": word.script_word_index,
        "token_index": word.token_index,
        "exact_text": word.exact_text,
        "char_start": word.char_start,
        "char_end": word.char_end,
        "cleaned_start_sample": word.cleaned_start_sample,
        "cleaned_end_sample": word.cleaned_end_sample,
        "original_start_sample": word.original_start_sample,
        "original_end_sample": word.original_end_sample,
        "timing_status": word.timing_status.value,
        "match_type": word.match_type.value,
        "matched_recognition_indices": list(word.matched_recognition_indices),
        "alignment_operation_id": word.alignment_operation_id,
        "interpolation_left_anchor_script_word_index": (
            word.interpolation_left_anchor_script_word_index
        ),
        "interpolation_right_anchor_script_word_index": (
            word.interpolation_right_anchor_script_word_index
        ),
        "text_similarity": _optional_fraction(word.text_similarity),
        "alignment_score": _optional_fraction(word.alignment_score),
        "asr_confidence": word.asr_confidence,
        "warnings": list(word.warnings),
    }


def _unmatched_to_dict(word: UnmatchedAsrWord) -> dict[str, Any]:
    return {
        "recognition_index": word.recognition_index,
        "text": word.text,
        "cleaned_start_sample": word.cleaned_start_sample,
        "cleaned_end_sample": word.cleaned_end_sample,
        "original_start_sample": word.original_start_sample,
        "original_end_sample": word.original_end_sample,
        "confidence": word.confidence,
    }


def _rejected_to_dict(item: RejectedAsrEvidence) -> dict[str, Any]:
    return {
        "recognition_index": item.recognition_index,
        "text": item.text,
        "cleaned_start_sample": item.cleaned_start_sample,
        "cleaned_end_sample": item.cleaned_end_sample,
        "original_start_sample": item.original_start_sample,
        "original_end_sample": item.original_end_sample,
        "confidence": item.confidence,
        "rejection_reason": item.rejection_reason,
        "related_script_word_indices": list(item.related_script_word_indices),
        "attempted_match_type": item.attempted_match_type.value,
        "attempted_operation_id": item.attempted_operation_id,
    }


def _diagnostics_to_dict(value: AlignmentDiagnostics) -> dict[str, Any]:
    return {
        "total_script_words": value.total_script_words,
        "total_asr_words": value.total_asr_words,
        "exact_matches": value.exact_matches,
        "normalized_matches": value.normalized_matches,
        "fuzzy_matches": value.fuzzy_matches,
        "split_merge_matches": value.split_merge_matches,
        "substitutions": value.substitutions,
        "interpolated_words": value.interpolated_words,
        "unresolved_script_words": value.unresolved_script_words,
        "unmatched_asr_words": value.unmatched_asr_words,
        "rejected_asr_evidence_count": value.rejected_asr_evidence_count,
        "classified_asr_words": value.classified_asr_words,
        "provenance_complete": value.provenance_complete,
        "observed_timing_coverage": _fraction(value.observed_timing_coverage),
        "total_timing_coverage": _fraction(value.total_timing_coverage),
        "text_alignment_coverage": _fraction(value.text_alignment_coverage),
    }


def _diagnostics_from_dict(value: dict[str, Any]) -> AlignmentDiagnostics:
    return AlignmentDiagnostics(
        total_script_words=_integer(value, "total_script_words"),
        total_asr_words=_integer(value, "total_asr_words"),
        exact_matches=_integer(value, "exact_matches"),
        normalized_matches=_integer(value, "normalized_matches"),
        fuzzy_matches=_integer(value, "fuzzy_matches"),
        split_merge_matches=_integer(value, "split_merge_matches"),
        substitutions=_integer(value, "substitutions"),
        interpolated_words=_integer(value, "interpolated_words"),
        unresolved_script_words=_integer(value, "unresolved_script_words"),
        unmatched_asr_words=_integer(value, "unmatched_asr_words"),
        rejected_asr_evidence_count=_integer(value, "rejected_asr_evidence_count"),
        classified_asr_words=_integer(value, "classified_asr_words"),
        provenance_complete=_boolean(value, "provenance_complete"),
        observed_timing_coverage=_fraction_from_dict(
            value.get("observed_timing_coverage")
        ),
        total_timing_coverage=_fraction_from_dict(value.get("total_timing_coverage")),
        text_alignment_coverage=_fraction_from_dict(
            value.get("text_alignment_coverage")
        ),
    )


def _token_from_dict(payload: Any) -> ScriptToken:
    value = _mapping(payload, "token")
    raw_key = value.get("comparison_key")
    if raw_key is not None and (not isinstance(raw_key, str) or not raw_key):
        raise TypeError("comparison_key must be null or non-empty")
    return ScriptToken(
        token_index=_integer(value, "token_index"),
        kind=ScriptTokenKind(_string(value, "kind")),
        exact_text=_string(value, "exact_text"),
        char_start=_integer(value, "char_start"),
        char_end=_integer(value, "char_end"),
        comparison_key=raw_key,
    )


def _aligned_word_from_dict(payload: Any) -> AlignedScriptWord:
    value = _mapping(payload, "aligned word")
    return AlignedScriptWord(
        script_word_index=_integer(value, "script_word_index"),
        token_index=_integer(value, "token_index"),
        exact_text=_string(value, "exact_text"),
        char_start=_integer(value, "char_start"),
        char_end=_integer(value, "char_end"),
        cleaned_start_sample=_optional_integer(value, "cleaned_start_sample"),
        cleaned_end_sample=_optional_integer(value, "cleaned_end_sample"),
        original_start_sample=_optional_integer(value, "original_start_sample"),
        original_end_sample=_optional_integer(value, "original_end_sample"),
        timing_status=TimingStatus(_string(value, "timing_status")),
        match_type=AlignmentMatchType(_string(value, "match_type")),
        matched_recognition_indices=tuple(
            _plain_integer(item, "recognition index")
            for item in _array(value, "matched_recognition_indices")
        ),
        alignment_operation_id=_optional_string(value, "alignment_operation_id"),
        interpolation_left_anchor_script_word_index=_optional_integer(
            value, "interpolation_left_anchor_script_word_index"
        ),
        interpolation_right_anchor_script_word_index=_optional_integer(
            value, "interpolation_right_anchor_script_word_index"
        ),
        text_similarity=_optional_fraction_from_dict(value.get("text_similarity")),
        alignment_score=_optional_fraction_from_dict(value.get("alignment_score")),
        asr_confidence=_optional_number(value, "asr_confidence"),
        warnings=_string_array(value, "warnings"),
    )


def _unmatched_from_dict(payload: Any) -> UnmatchedAsrWord:
    value = _mapping(payload, "unmatched ASR word")
    return UnmatchedAsrWord(
        recognition_index=_integer(value, "recognition_index"),
        text=_string(value, "text"),
        cleaned_start_sample=_integer(value, "cleaned_start_sample"),
        cleaned_end_sample=_integer(value, "cleaned_end_sample"),
        original_start_sample=_integer(value, "original_start_sample"),
        original_end_sample=_integer(value, "original_end_sample"),
        confidence=_optional_number(value, "confidence"),
    )


def _rejected_from_dict(payload: Any) -> RejectedAsrEvidence:
    value = _mapping(payload, "rejected ASR evidence")
    return RejectedAsrEvidence(
        recognition_index=_integer(value, "recognition_index"),
        text=_string(value, "text"),
        cleaned_start_sample=_integer(value, "cleaned_start_sample"),
        cleaned_end_sample=_integer(value, "cleaned_end_sample"),
        original_start_sample=_integer(value, "original_start_sample"),
        original_end_sample=_integer(value, "original_end_sample"),
        confidence=_optional_number(value, "confidence"),
        rejection_reason=_string(value, "rejection_reason"),
        related_script_word_indices=tuple(
            _plain_integer(item, "script word index")
            for item in _array(value, "related_script_word_indices")
        ),
        attempted_match_type=AlignmentMatchType(
            _string(value, "attempted_match_type")
        ),
        attempted_operation_id=_string(value, "attempted_operation_id"),
    )


def _fraction(value: Fraction) -> dict[str, int | str]:
    with localcontext() as context:
        context.prec = 28
        decimal = Decimal(value.numerator) / Decimal(value.denominator)
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": str(decimal),
    }


def _optional_fraction(value: Fraction | None) -> dict[str, int | str] | None:
    return None if value is None else _fraction(value)


def _fraction_from_dict(payload: Any) -> Fraction:
    value = _mapping(payload, "fraction")
    numerator = _integer(value, "numerator")
    denominator = _integer(value, "denominator")
    if denominator <= 0:
        raise ValueError("fraction denominator must be positive")
    result = Fraction(numerator, denominator)
    decimal_text = value.get("decimal")
    if not isinstance(decimal_text, str):
        raise TypeError("fraction decimal must be a string")
    try:
        decimal = Decimal(decimal_text)
    except InvalidOperation as exc:
        raise ValueError("fraction decimal must be finite") from exc
    if not decimal.is_finite() or decimal_text != _fraction(result)["decimal"]:
        raise ValueError("fraction decimal is inconsistent")
    return result


def _optional_fraction_from_dict(payload: Any) -> Fraction | None:
    return None if payload is None else _fraction_from_dict(payload)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _array(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array")
    return value


def _string_array(data: dict[str, Any], key: str) -> tuple[str, ...]:
    values = _array(data, key)
    if not all(isinstance(item, str) for item in values):
        raise TypeError(f"{key} must contain strings")
    return tuple(values)


def _string_mapping(value: Any, name: str) -> dict[str, str]:
    mapping = _mapping(value, name)
    if not all(
        isinstance(key, str) and key and isinstance(item, str) and item
        for key, item in mapping.items()
    ):
        raise TypeError(f"{name} must contain non-empty string pairs")
    return mapping


def _plain_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _integer(data: dict[str, Any], key: str) -> int:
    return _plain_integer(data.get(key), key)


def _optional_integer(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    return None if value is None else _plain_integer(value, key)


def _string(
    data: dict[str, Any], key: str, *, allow_empty: bool = False
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise TypeError(f"{key} must be null or non-empty string")
    return value


def _boolean(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be boolean")
    return value


def _optional_number(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be null or number")
    return float(value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")
