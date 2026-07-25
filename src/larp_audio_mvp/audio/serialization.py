"""Explicit JSON-safe serialization for the technical inspection CLI."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import (
    AudioInfo,
    AudioLoadResult,
    EditKind,
    EditMap,
    EditSpan,
    PauseSegment,
    SampleRange,
)
from larp_audio_mvp.core.errors import EditMapError


def audio_load_result_to_dict(result: AudioLoadResult) -> dict[str, Any]:
    return {
        "source_audio": audio_info_to_dict(result.source_audio),
        "canonical_audio": audio_info_to_dict(result.canonical_audio),
    }


def audio_info_to_dict(audio: AudioInfo) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for item in fields(audio):
        value = getattr(audio, item.name)
        serialized[item.name] = _json_value(value)
    return serialized


def pause_detection_to_dict(
    audio: AudioInfo,
    settings: PauseSettings,
    segments: list[PauseSegment],
) -> dict[str, Any]:
    return {
        "sample_rate": audio.sample_rate,
        "total_samples": audio.total_samples,
        "settings": {
            "silence_threshold_db": (
                None
                if settings.silence_threshold_db is None
                else format(settings.silence_threshold_db, "f")
            ),
            "minimum_pause_duration_ms": settings.minimum_pause_duration_ms,
        },
        "pauses": [pause_segment_to_dict(segment) for segment in segments],
    }


def pause_segment_to_dict(segment: PauseSegment) -> dict[str, Any]:
    return {
        "start_sample": segment.start_sample,
        "end_sample": segment.end_sample,
        "length_samples": segment.length_samples,
        "start_seconds": _json_value(segment.start_seconds),
        "end_seconds": _json_value(segment.end_seconds),
        "duration_seconds": _json_value(segment.duration_seconds),
    }


def edit_map_to_dict(edit_map: EditMap) -> dict[str, Any]:
    return {
        "schema_version": edit_map.schema_version,
        "policy": {
            "version": edit_map.policy_version,
            "parameters": dict(edit_map.policy_snapshot),
        },
        "audio": {
            "sample_rate": edit_map.sample_rate,
            "source_total_samples": edit_map.source_total_samples,
            "target_total_samples": edit_map.output_total_samples,
            "removed_samples": edit_map.removed_samples,
            "source_sha256": edit_map.source_sha256,
            "target_sha256": edit_map.output_sha256,
        },
        "spans": [edit_span_to_dict(span) for span in edit_map.spans],
        "warnings": list(edit_map.warnings),
    }


def edit_span_to_dict(span: EditSpan) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": span.kind.value,
        "source_start": span.source_start,
        "source_end": span.source_end,
        "target_start": span.target_start,
        "target_end": span.target_end,
        "removed_samples": span.removed_samples,
        "reason": span.reason,
    }
    if span.candidate_range is not None:
        value["candidate"] = {
            "source_start": span.candidate_range.start,
            "source_end": span.candidate_range.end,
        }
        value["retained_before_samples"] = span.retained_before_samples
        value["retained_after_samples"] = span.retained_after_samples
    return value


def write_edit_map_atomic(edit_map: EditMap, destination: Path) -> None:
    """Write deterministic UTF-8 JSON beside its final path, then replace."""

    if not edit_map.output_sha256:
        raise EditMapError(
            "persisted edit map requires target SHA-256",
            code="MISSING_OUTPUT_HASH",
        )
    destination = destination.expanduser().resolve()
    if destination.suffix.lower() != ".json":
        raise EditMapError(
            "edit map destination must use .json",
            code="INVALID_EDIT_MAP_EXTENSION",
        )
    if destination.exists() and destination.is_dir():
        raise EditMapError(
            "edit map destination is a directory",
            code="EDIT_MAP_OUTPUT_IS_DIRECTORY",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=".partial.json",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                edit_map_to_dict(edit_map),
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    except OSError as exc:
        raise EditMapError(
            f"cannot publish edit map: {destination.name}",
            code="EDIT_MAP_PUBLISH_FAILED",
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def read_edit_map(source: Path) -> EditMap:
    """Read and validate the exact Stage 6 persisted edit-map schema."""

    source = source.expanduser().resolve()
    try:
        with source.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EditMapError(
            f"cannot read edit map: {source.name}", code="EDIT_MAP_READ_FAILED"
        ) from exc
    try:
        return edit_map_from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise EditMapError(
            "edit map JSON does not satisfy schema version 1",
            code="INVALID_EDIT_MAP",
        ) from exc


def edit_map_from_dict(payload: Any) -> EditMap:
    root = _mapping(payload, "edit map")
    policy = _mapping(root.get("policy"), "policy")
    audio = _mapping(root.get("audio"), "audio")
    parameters = _mapping(policy.get("parameters"), "policy parameters")
    raw_spans = root.get("spans")
    if not isinstance(raw_spans, list):
        raise TypeError("spans must be an array")

    spans: list[EditSpan] = []
    for raw_span in raw_spans:
        item = _mapping(raw_span, "span")
        kind = EditKind(_string_value(item, "kind"))
        source_range = SampleRange(
            _integer_value(item, "source_start"),
            _integer_value(item, "source_end"),
        )
        target_start = _integer_value(item, "target_start")
        target_end = _integer_value(item, "target_end")
        reason = _string_value(item, "reason")
        if kind is EditKind.KEEP:
            span = EditSpan(
                kind=kind,
                source_range=source_range,
                output_range=SampleRange(target_start, target_end),
                reason=reason,
            )
            if _integer_value(item, "removed_samples") != span.removed_samples:
                raise ValueError("kept span removed_samples must be zero")
            spans.append(span)
            continue

        candidate = _mapping(item.get("candidate"), "candidate")
        span = EditSpan(
            kind=kind,
            source_range=source_range,
            target_anchor=target_start,
            candidate_range=SampleRange(
                _integer_value(candidate, "source_start"),
                _integer_value(candidate, "source_end"),
            ),
            retained_before_samples=_integer_value(
                item, "retained_before_samples"
            ),
            retained_after_samples=_integer_value(
                item, "retained_after_samples"
            ),
            reason=reason,
        )
        if _integer_value(item, "removed_samples") != span.removed_samples:
            raise ValueError("removed span sample count does not match its range")
        spans.append(span)
        if target_end != target_start:
            raise ValueError("removed span target must collapse to one anchor")

    warnings = root.get("warnings", [])
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) for item in warnings
    ):
        raise TypeError("warnings must be an array of strings")
    policy_snapshot = tuple(
        sorted(
            (
                key,
                _plain_integer(value, f"policy parameter {key}"),
            )
            for key, value in parameters.items()
            if isinstance(key, str) and key
        )
    )
    if len(policy_snapshot) != len(parameters):
        raise TypeError("policy parameter names must be non-empty strings")

    edit_map = EditMap(
        schema_version=_string_value(root, "schema_version"),
        policy_version=_string_value(policy, "version"),
        sample_rate=_integer_value(audio, "sample_rate"),
        source_total_samples=_integer_value(audio, "source_total_samples"),
        output_total_samples=_integer_value(audio, "target_total_samples"),
        source_sha256=_string_value(audio, "source_sha256"),
        output_sha256=_optional_string_value(audio, "target_sha256"),
        spans=tuple(spans),
        policy_snapshot=policy_snapshot,
        warnings=tuple(warnings),
    )
    if _integer_value(audio, "removed_samples") != edit_map.removed_samples:
        raise ValueError("audio removed_samples does not match timeline totals")
    return edit_map


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _plain_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _integer_value(data: dict[str, Any], key: str) -> int:
    return _plain_integer(data.get(key), key)


def _string_value(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} must be a non-empty string")
    return value


def _optional_string_value(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} must be null or a non-empty string")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Fraction):
        with localcontext() as context:
            context.prec = 28
            decimal = Decimal(value.numerator) / Decimal(value.denominator)
        return {
            "numerator": value.numerator,
            "denominator": value.denominator,
            "decimal": str(decimal),
        }
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
