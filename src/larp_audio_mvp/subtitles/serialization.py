"""Deterministic JSON persistence for ``subtitle_blocks.schema.v1``."""

from __future__ import annotations

import json
import io
import os
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from larp_audio_mvp.core.contracts import (
    SubtitleBlock,
    SubtitleDiagnostics,
    SubtitleDocument,
    SubtitleTimingProvenance,
)
from larp_audio_mvp.core.errors import (
    SubtitleSerializationError,
    SubtitleValidationError,
)
from larp_audio_mvp.subtitles.validation import (
    SUBTITLE_SCHEMA_VERSION,
    validate_subtitle_document,
)


def _fraction_to_dict(value: Fraction) -> dict[str, int | str]:
    decimal = Decimal(value.numerator) / Decimal(value.denominator)
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": format(decimal.normalize(), "f"),
    }


def _fraction_from_dict(value: Any, *, field: str) -> Fraction:
    if not isinstance(value, dict):
        raise SubtitleSerializationError(
            f"{field} must be a rational object", code="INVALID_SUBTITLE_RATIONAL"
        )
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    decimal_text = value.get("decimal")
    if (
        isinstance(numerator, bool)
        or not isinstance(numerator, int)
        or isinstance(denominator, bool)
        or not isinstance(denominator, int)
        or denominator <= 0
        or not isinstance(decimal_text, str)
    ):
        raise SubtitleSerializationError(
            f"{field} contains an invalid rational value",
            code="INVALID_SUBTITLE_RATIONAL",
        )
    result = Fraction(numerator, denominator)
    try:
        decimal = Decimal(decimal_text)
        expected = Decimal(result.numerator) / Decimal(result.denominator)
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        raise SubtitleSerializationError(
            f"{field} contains an invalid decimal",
            code="INVALID_SUBTITLE_RATIONAL",
        ) from exc
    if not decimal.is_finite() or decimal != expected:
        raise SubtitleSerializationError(
            f"{field} decimal does not match its fraction",
            code="INVALID_SUBTITLE_RATIONAL",
        )
    return result


def subtitle_document_to_dict(document: SubtitleDocument) -> dict[str, Any]:
    validate_subtitle_document(document)
    return {
        "schema_version": document.schema_version,
        "source_alignment_schema_version": document.source_alignment_schema_version,
        "source_alignment_sha256": document.source_alignment_sha256,
        "script": {
            "source_sha256": document.script_sha256,
            "encoding": document.script_encoding,
            "has_bom": document.script_has_bom,
            "exact_text": document.exact_script_text,
        },
        "sample_rate": document.sample_rate,
        "cleaned_total_samples": document.cleaned_total_samples,
        "original_total_samples": document.original_total_samples,
        "configuration": dict(document.configuration_snapshot),
        "blocks": [_block_to_dict(block) for block in document.blocks],
        "diagnostics": _diagnostics_to_dict(document.diagnostics),
        "warnings": list(document.warnings),
    }


def _block_to_dict(block: SubtitleBlock) -> dict[str, Any]:
    return {
        "block_index": block.block_index,
        "source_char_start": block.source_char_start,
        "source_char_end": block.source_char_end,
        "source_text_exact": block.source_text_exact,
        "display_lines": list(block.display_lines),
        "first_token_index": block.first_token_index,
        "last_token_index": block.last_token_index,
        "script_word_indices": list(block.script_word_indices),
        "interpolated_script_word_indices": list(
            block.interpolated_script_word_indices
        ),
        "unresolved_script_word_indices": list(
            block.unresolved_script_word_indices
        ),
        "cleaned_start_sample": block.cleaned_start_sample,
        "cleaned_end_sample": block.cleaned_end_sample,
        "original_start_sample": block.original_start_sample,
        "original_end_sample": block.original_end_sample,
        "duration_samples": block.duration_samples,
        "word_count": block.word_count,
        "visible_character_count": block.visible_character_count,
        "characters_per_second": _fraction_to_dict(
            block.characters_per_second
        ),
        "timing_provenance": block.timing_provenance.value,
        "contains_interpolated_words": block.contains_interpolated_words,
        "contains_unresolved_words": block.contains_unresolved_words,
        "warnings": list(block.warnings),
    }


def _diagnostics_to_dict(value: SubtitleDiagnostics) -> dict[str, Any]:
    return {
        "total_blocks": value.total_blocks,
        "total_script_words": value.total_script_words,
        "exported_script_words": value.exported_script_words,
        "unresolved_script_words": value.unresolved_script_words,
        "attached_unresolved_words": value.attached_unresolved_words,
        "interpolated_script_words": value.interpolated_script_words,
        "blocks_with_interpolated_words": value.blocks_with_interpolated_words,
        "blocks_with_unresolved_words": value.blocks_with_unresolved_words,
        "average_block_duration": _fraction_to_dict(
            value.average_block_duration
        ),
        "maximum_block_duration": _fraction_to_dict(
            value.maximum_block_duration
        ),
        "average_characters_per_second": _fraction_to_dict(
            value.average_characters_per_second
        ),
        "maximum_characters_per_second": _fraction_to_dict(
            value.maximum_characters_per_second
        ),
        "blocks_over_cps_limit": value.blocks_over_cps_limit,
        "blocks_over_duration_limit": value.blocks_over_duration_limit,
        "blocks_over_line_length_limit": value.blocks_over_line_length_limit,
        "single_word_blocks": value.single_word_blocks,
        "short_blocks": value.short_blocks,
        "average_words_per_block": _fraction_to_dict(
            value.average_words_per_block
        ),
        "minimum_words_in_block": value.minimum_words_in_block,
        "maximum_words_in_block": value.maximum_words_in_block,
        "blocks_created_at_sentence_boundary": (
            value.blocks_created_at_sentence_boundary
        ),
        "blocks_created_at_comma_boundary": value.blocks_created_at_comma_boundary,
        "blocks_created_at_gap_boundary": value.blocks_created_at_gap_boundary,
        "blocks_forced_by_hard_limit": value.blocks_forced_by_hard_limit,
        "text_coverage": _fraction_to_dict(value.text_coverage),
        "timing_coverage": _fraction_to_dict(value.timing_coverage),
        "srt_exportable": value.srt_exportable,
        "warnings_count": value.warnings_count,
        "internal_gap_count": value.internal_gap_count,
        "srt_gap_count": value.srt_gap_count,
        "overlap_count": value.overlap_count,
        "maximum_internal_gap_ms": value.maximum_internal_gap_ms,
        "maximum_srt_gap_ms": value.maximum_srt_gap_ms,
        "list_item_count": value.list_item_count,
        "list_item_merge_violation_count": value.list_item_merge_violation_count,
        "protected_unit_count": value.protected_unit_count,
        "protected_unit_violation_count": value.protected_unit_violation_count,
        "adjective_noun_split_count": value.adjective_noun_split_count,
        "verb_object_split_count": value.verb_object_split_count,
        "phrasal_verb_split_count": value.phrasal_verb_split_count,
        "preposition_object_split_count": value.preposition_object_split_count,
        "number_unit_split_count": value.number_unit_split_count,
        "product_name_split_count": value.product_name_split_count,
        "maximum_display_characters": value.maximum_display_characters,
        "orphan_fragment_count": value.orphan_fragment_count,
        "incomplete_ending_count": value.incomplete_ending_count,
        "trailing_period_violation_count": value.trailing_period_violation_count,
        "trailing_comma_violation_count": value.trailing_comma_violation_count,
        "three_line_cue_count": value.three_line_cue_count,
        "empty_line_count": value.empty_line_count,
        "maximum_plain_characters": value.maximum_plain_characters,
        "maximum_render_line_characters": value.maximum_render_line_characters,
        "cue_count": value.cue_count,
        "two_line_cue_count": value.two_line_cue_count,
        "forced_syntax_split_count": value.forced_syntax_split_count,
        "auxiliary_verb_split_count": value.auxiliary_verb_split_count,
        "verb_particle_split_count": value.verb_particle_split_count,
        "compound_noun_split_count": value.compound_noun_split_count,
        "degree_modifier_split_count": value.degree_modifier_split_count,
        "temporal_connector_split_count": value.temporal_connector_split_count,
        "proper_name_split_count": value.proper_name_split_count,
        "semantic_cue_count": value.semantic_cue_count,
        "unnecessary_split_count": value.unnecessary_split_count,
        "required_boundary_miss_count": value.required_boundary_miss_count,
        "list_item_internal_split_count": value.list_item_internal_split_count,
        "orphan_beginning_count": value.orphan_beginning_count,
        "wh_clause_split_count": value.wh_clause_split_count,
        "or_not_split_count": value.or_not_split_count,
        "parser_low_confidence_split_count": (
            value.parser_low_confidence_split_count
        ),
    }


def write_subtitle_document(document: SubtitleDocument, path: Path) -> None:
    encoded = render_subtitle_document_json(document)
    destination = path.expanduser().resolve()
    partial = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with partial.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, destination)
    except (OSError, TypeError, ValueError) as exc:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise SubtitleSerializationError(
            f"cannot write subtitle document: {destination.name}",
            code="SUBTITLE_JSON_WRITE_FAILED",
        ) from exc


def render_subtitle_document_json(document: SubtitleDocument) -> bytes:
    payload = subtitle_document_to_dict(document)
    stream = io.StringIO(newline="")
    json.dump(
        payload,
        stream,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    stream.write("\n")
    return stream.getvalue().encode("utf-8")


def read_subtitle_document(path: Path) -> SubtitleDocument:
    source = path.expanduser().resolve()
    try:
        with source.open("r", encoding="utf-8", newline="") as stream:
            payload = json.load(
                stream,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON number: {value}")
                ),
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SubtitleSerializationError(
            f"cannot read subtitle document: {source.name}",
            code="SUBTITLE_JSON_READ_FAILED",
        ) from exc
    return subtitle_document_from_dict(payload)


def subtitle_document_from_dict(payload: Any) -> SubtitleDocument:
    try:
        root = _mapping(payload, "root")
        schema_version = _string(root, "schema_version")
        if schema_version != SUBTITLE_SCHEMA_VERSION:
            raise SubtitleSerializationError(
                f"unsupported subtitle schema: {schema_version}",
                code="UNSUPPORTED_SUBTITLE_SCHEMA",
            )
        script = _mapping(root.get("script"), "script")
        configuration = _mapping(root.get("configuration"), "configuration")
        blocks_value = root.get("blocks")
        if not isinstance(blocks_value, list):
            raise TypeError("blocks must be a list")
        warnings = _string_tuple(root.get("warnings"), "warnings")
        document = SubtitleDocument(
            schema_version=schema_version,
            source_alignment_schema_version=_string(
                root, "source_alignment_schema_version"
            ),
            source_alignment_sha256=_string(root, "source_alignment_sha256"),
            script_sha256=_string(script, "source_sha256"),
            script_encoding=_string(script, "encoding"),
            script_has_bom=_boolean(script, "has_bom"),
            exact_script_text=_string(script, "exact_text", allow_empty=False),
            sample_rate=_integer(root, "sample_rate"),
            cleaned_total_samples=_integer(root, "cleaned_total_samples"),
            original_total_samples=_integer(root, "original_total_samples"),
            configuration_snapshot=tuple(
                sorted(
                    (
                        str(key),
                        value if isinstance(value, str) else _raise_type(),
                    )
                    for key, value in configuration.items()
                )
            ),
            blocks=tuple(_block_from_dict(item) for item in blocks_value),
            diagnostics=_diagnostics_from_dict(
                _mapping(root.get("diagnostics"), "diagnostics")
            ),
            warnings=warnings,
        )
        validate_subtitle_document(document)
        return document
    except (SubtitleSerializationError, SubtitleValidationError):
        raise
    except Exception as exc:
        raise SubtitleSerializationError(
            "invalid subtitle_blocks JSON",
            code="INVALID_SUBTITLE_JSON",
        ) from exc


def _block_from_dict(value: Any) -> SubtitleBlock:
    data = _mapping(value, "block")
    return SubtitleBlock(
        block_index=_integer(data, "block_index"),
        source_char_start=_integer(data, "source_char_start"),
        source_char_end=_integer(data, "source_char_end"),
        source_text_exact=_string(data, "source_text_exact"),
        display_lines=_string_tuple(data.get("display_lines"), "display_lines"),
        first_token_index=_integer(data, "first_token_index"),
        last_token_index=_integer(data, "last_token_index"),
        script_word_indices=_integer_tuple(
            data.get("script_word_indices"), "script_word_indices"
        ),
        interpolated_script_word_indices=_integer_tuple(
            data.get("interpolated_script_word_indices"),
            "interpolated_script_word_indices",
        ),
        unresolved_script_word_indices=_integer_tuple(
            data.get("unresolved_script_word_indices"),
            "unresolved_script_word_indices",
        ),
        cleaned_start_sample=_integer(data, "cleaned_start_sample"),
        cleaned_end_sample=_integer(data, "cleaned_end_sample"),
        original_start_sample=_integer(data, "original_start_sample"),
        original_end_sample=_integer(data, "original_end_sample"),
        duration_samples=_integer(data, "duration_samples"),
        word_count=_integer(data, "word_count"),
        visible_character_count=_integer(data, "visible_character_count"),
        characters_per_second=_fraction_from_dict(
            data.get("characters_per_second"), field="characters_per_second"
        ),
        timing_provenance=SubtitleTimingProvenance(
            _string(data, "timing_provenance")
        ),
        contains_interpolated_words=_boolean(
            data, "contains_interpolated_words"
        ),
        contains_unresolved_words=_boolean(data, "contains_unresolved_words"),
        warnings=_string_tuple(data.get("warnings"), "block warnings"),
    )


def _diagnostics_from_dict(data: Mapping[str, Any]) -> SubtitleDiagnostics:
    return SubtitleDiagnostics(
        total_blocks=_integer(data, "total_blocks"),
        total_script_words=_integer(data, "total_script_words"),
        exported_script_words=_integer(data, "exported_script_words"),
        unresolved_script_words=_integer(data, "unresolved_script_words"),
        attached_unresolved_words=_integer(data, "attached_unresolved_words"),
        interpolated_script_words=_integer(data, "interpolated_script_words"),
        blocks_with_interpolated_words=_integer(
            data, "blocks_with_interpolated_words"
        ),
        blocks_with_unresolved_words=_integer(data, "blocks_with_unresolved_words"),
        average_block_duration=_fraction_from_dict(
            data.get("average_block_duration"), field="average_block_duration"
        ),
        maximum_block_duration=_fraction_from_dict(
            data.get("maximum_block_duration"), field="maximum_block_duration"
        ),
        average_characters_per_second=_fraction_from_dict(
            data.get("average_characters_per_second"),
            field="average_characters_per_second",
        ),
        maximum_characters_per_second=_fraction_from_dict(
            data.get("maximum_characters_per_second"),
            field="maximum_characters_per_second",
        ),
        blocks_over_cps_limit=_integer(data, "blocks_over_cps_limit"),
        blocks_over_duration_limit=_integer(data, "blocks_over_duration_limit"),
        blocks_over_line_length_limit=_integer(
            data, "blocks_over_line_length_limit"
        ),
        single_word_blocks=_integer(data, "single_word_blocks"),
        short_blocks=_integer(data, "short_blocks"),
        average_words_per_block=_fraction_from_dict(
            data.get("average_words_per_block"), field="average_words_per_block"
        ),
        minimum_words_in_block=_integer(data, "minimum_words_in_block"),
        maximum_words_in_block=_integer(data, "maximum_words_in_block"),
        blocks_created_at_sentence_boundary=_integer(
            data, "blocks_created_at_sentence_boundary"
        ),
        blocks_created_at_comma_boundary=_integer(
            data, "blocks_created_at_comma_boundary"
        ),
        blocks_created_at_gap_boundary=_integer(
            data, "blocks_created_at_gap_boundary"
        ),
        blocks_forced_by_hard_limit=_integer(data, "blocks_forced_by_hard_limit"),
        text_coverage=_fraction_from_dict(
            data.get("text_coverage"), field="text_coverage"
        ),
        timing_coverage=_fraction_from_dict(
            data.get("timing_coverage"), field="timing_coverage"
        ),
        srt_exportable=_boolean(data, "srt_exportable"),
        warnings_count=_integer(data, "warnings_count"),
        internal_gap_count=_optional_nonnegative_integer(
            data, "internal_gap_count"
        ),
        srt_gap_count=_optional_nonnegative_integer(data, "srt_gap_count"),
        overlap_count=_optional_nonnegative_integer(data, "overlap_count"),
        maximum_internal_gap_ms=_optional_nonnegative_integer(
            data, "maximum_internal_gap_ms"
        ),
        maximum_srt_gap_ms=_optional_nonnegative_integer(
            data, "maximum_srt_gap_ms"
        ),
        list_item_count=_optional_nonnegative_integer(data, "list_item_count"),
        list_item_merge_violation_count=_optional_nonnegative_integer(
            data, "list_item_merge_violation_count"
        ),
        protected_unit_count=_optional_nonnegative_integer(
            data, "protected_unit_count"
        ),
        protected_unit_violation_count=_optional_nonnegative_integer(
            data, "protected_unit_violation_count"
        ),
        adjective_noun_split_count=_optional_nonnegative_integer(
            data, "adjective_noun_split_count"
        ),
        verb_object_split_count=_optional_nonnegative_integer(
            data, "verb_object_split_count"
        ),
        phrasal_verb_split_count=_optional_nonnegative_integer(
            data, "phrasal_verb_split_count"
        ),
        preposition_object_split_count=_optional_nonnegative_integer(
            data, "preposition_object_split_count"
        ),
        number_unit_split_count=_optional_nonnegative_integer(
            data, "number_unit_split_count"
        ),
        product_name_split_count=_optional_nonnegative_integer(
            data, "product_name_split_count"
        ),
        maximum_display_characters=_optional_nonnegative_integer(
            data, "maximum_display_characters"
        ),
        orphan_fragment_count=_optional_nonnegative_integer(
            data, "orphan_fragment_count"
        ),
        incomplete_ending_count=_optional_nonnegative_integer(
            data, "incomplete_ending_count"
        ),
        trailing_period_violation_count=_optional_nonnegative_integer(
            data, "trailing_period_violation_count"
        ),
        trailing_comma_violation_count=_optional_nonnegative_integer(
            data, "trailing_comma_violation_count"
        ),
        three_line_cue_count=_optional_nonnegative_integer(
            data, "three_line_cue_count"
        ),
        empty_line_count=_optional_nonnegative_integer(data, "empty_line_count"),
        maximum_plain_characters=_optional_nonnegative_integer(
            data, "maximum_plain_characters"
        ),
        maximum_render_line_characters=_optional_nonnegative_integer(
            data, "maximum_render_line_characters"
        ),
        cue_count=_optional_nonnegative_integer(data, "cue_count"),
        two_line_cue_count=_optional_nonnegative_integer(
            data, "two_line_cue_count"
        ),
        forced_syntax_split_count=_optional_nonnegative_integer(
            data, "forced_syntax_split_count"
        ),
        auxiliary_verb_split_count=_optional_nonnegative_integer(
            data, "auxiliary_verb_split_count"
        ),
        verb_particle_split_count=_optional_nonnegative_integer(
            data, "verb_particle_split_count"
        ),
        compound_noun_split_count=_optional_nonnegative_integer(
            data, "compound_noun_split_count"
        ),
        degree_modifier_split_count=_optional_nonnegative_integer(
            data, "degree_modifier_split_count"
        ),
        temporal_connector_split_count=_optional_nonnegative_integer(
            data, "temporal_connector_split_count"
        ),
        proper_name_split_count=_optional_nonnegative_integer(
            data, "proper_name_split_count"
        ),
        semantic_cue_count=_optional_nonnegative_integer(
            data, "semantic_cue_count"
        ),
        unnecessary_split_count=_optional_nonnegative_integer(
            data, "unnecessary_split_count"
        ),
        required_boundary_miss_count=_optional_nonnegative_integer(
            data, "required_boundary_miss_count"
        ),
        list_item_internal_split_count=_optional_nonnegative_integer(
            data, "list_item_internal_split_count"
        ),
        orphan_beginning_count=_optional_nonnegative_integer(
            data, "orphan_beginning_count"
        ),
        wh_clause_split_count=_optional_nonnegative_integer(
            data, "wh_clause_split_count"
        ),
        or_not_split_count=_optional_nonnegative_integer(
            data, "or_not_split_count"
        ),
        parser_low_confidence_split_count=_optional_nonnegative_integer(
            data, "parser_low_confidence_split_count"
        ),
    )


def _optional_nonnegative_integer(
    data: Mapping[str, Any], key: str
) -> int:
    if key not in data:
        return 0  # Stage 14.1 and older read-only compatibility.
    value = _integer(data, key)
    if value < 0:
        raise SubtitleSerializationError(
            f"{key} must be non-negative", code="INVALID_SUBTITLE_JSON"
        )
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object")
    return value


def _string(
    data: Mapping[str, Any], key: str, *, allow_empty: bool = False
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypeError(f"{key} must be a non-empty string")
    return value


def _integer(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _boolean(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be boolean")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{field} must be a string array")
    return tuple(value)


def _integer_tuple(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise TypeError(f"{field} must be an integer array")
    return tuple(value)


def _raise_type() -> str:
    raise TypeError("configuration values must be strings")
