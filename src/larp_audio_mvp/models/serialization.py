"""Deterministic, atomic serialization of recognition timing evidence."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

from larp_audio_mvp.core.contracts import RecognitionResult, RecognizedWord
from larp_audio_mvp.core.errors import (
    RecognitionCompatibilityError,
    RecognitionSerializationError,
)


def recognition_to_dict(result: RecognitionResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "backend": result.backend,
        "model": result.model,
        "language": result.language,
        "duration": {
            "cleaned_samples": result.duration_samples_cleaned,
            "cleaned_seconds": _fraction(result.duration),
            "original_samples": result.duration_samples_original,
            "original_seconds": _fraction(result.duration_original),
        },
        "sample_rate": result.sample_rate,
        "words": [_word_to_dict(word) for word in result.words],
        "metadata": dict(result.metadata),
    }


def _word_to_dict(word: RecognizedWord) -> dict[str, Any]:
    return {
        "text": word.text,
        "start_seconds": _fraction(word.start_seconds),
        "end_seconds": _fraction(word.end_seconds),
        "start_sample_original": word.start_sample_original,
        "end_sample_original": word.end_sample_original,
        "start_sample_cleaned": word.start_sample_cleaned,
        "end_sample_cleaned": word.end_sample_cleaned,
        "start_seconds_original": _fraction(word.start_seconds_original),
        "end_seconds_original": _fraction(word.end_seconds_original),
        "confidence": word.confidence,
    }


def write_recognition_atomic(
    result: RecognitionResult, destination: Path
) -> None:
    destination = destination.expanduser().resolve()
    if destination.suffix.lower() != ".json":
        raise RecognitionSerializationError(
            "recognition destination must use .json",
            code="STT_INVALID_OUTPUT_EXTENSION",
        )
    if destination.exists() and destination.is_dir():
        raise RecognitionSerializationError(
            "recognition destination is a directory",
            code="STT_OUTPUT_IS_DIRECTORY",
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
                recognition_to_dict(result),
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
        raise RecognitionSerializationError(
            f"cannot publish recognition JSON: {destination.name}",
            code="STT_OUTPUT_PUBLISH_FAILED",
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def read_recognition(source: Path) -> RecognitionResult:
    """Read and validate the exact version-1 recognition interchange schema."""

    path = source.expanduser().resolve()
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecognitionCompatibilityError(
            f"cannot read recognition JSON: {path.name}",
            code="RECOGNITION_READ_FAILED",
        ) from exc
    try:
        return recognition_from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise RecognitionCompatibilityError(
            "recognition JSON does not satisfy schema version 1",
            code="INVALID_RECOGNITION",
        ) from exc


def recognition_from_dict(payload: Any) -> RecognitionResult:
    root = _mapping(payload, "recognition")
    if _string(root, "schema_version") != "1":
        raise ValueError("unsupported recognition schema version")
    duration = _mapping(root.get("duration"), "duration")
    sample_rate = _integer(root, "sample_rate")
    cleaned_samples = _integer(duration, "cleaned_samples")
    original_samples = _integer(duration, "original_samples")
    _validate_fraction(
        duration.get("cleaned_seconds"), Fraction(cleaned_samples, sample_rate)
    )
    _validate_fraction(
        duration.get("original_seconds"), Fraction(original_samples, sample_rate)
    )

    raw_words = root.get("words")
    if not isinstance(raw_words, list):
        raise TypeError("words must be an array")
    words: list[RecognizedWord] = []
    for raw_word in raw_words:
        item = _mapping(raw_word, "word")
        confidence = item.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float))
        ):
            raise TypeError("confidence must be null or a number")
        word = RecognizedWord(
            text=_string(item, "text", allow_whitespace=True),
            sample_rate=sample_rate,
            start_sample_original=_integer(item, "start_sample_original"),
            end_sample_original=_integer(item, "end_sample_original"),
            start_sample_cleaned=_integer(item, "start_sample_cleaned"),
            end_sample_cleaned=_integer(item, "end_sample_cleaned"),
            confidence=None if confidence is None else float(confidence),
        )
        _validate_fraction(item.get("start_seconds"), word.start_seconds)
        _validate_fraction(item.get("end_seconds"), word.end_seconds)
        _validate_fraction(
            item.get("start_seconds_original"), word.start_seconds_original
        )
        _validate_fraction(
            item.get("end_seconds_original"), word.end_seconds_original
        )
        words.append(word)

    raw_metadata = _mapping(root.get("metadata"), "metadata")
    metadata = tuple(
        sorted(
            (_metadata_string(key, value) for key, value in raw_metadata.items())
        )
    )
    language = root.get("language")
    if language is not None and (not isinstance(language, str) or not language):
        raise TypeError("language must be null or a non-empty string")
    return RecognitionResult(
        schema_version="1",
        backend=_string(root, "backend"),
        model=_string(root, "model"),
        language=language,
        sample_rate=sample_rate,
        duration_samples_cleaned=cleaned_samples,
        duration_samples_original=original_samples,
        words=tuple(words),
        metadata=metadata,
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


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _integer(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _string(
    data: dict[str, Any], key: str, *, allow_whitespace: bool = False
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise TypeError(f"{key} must be a non-empty string")
    if not allow_whitespace and not value.strip():
        raise TypeError(f"{key} must not be blank")
    return value


def _metadata_string(key: Any, value: Any) -> tuple[str, str]:
    if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
        raise TypeError("metadata must contain non-empty string pairs")
    return key, value


def _validate_fraction(payload: Any, expected: Fraction) -> None:
    value = _mapping(payload, "exact fraction")
    numerator = _integer(value, "numerator")
    denominator = _integer(value, "denominator")
    if denominator <= 0 or Fraction(numerator, denominator) != expected:
        raise ValueError("fraction does not match authoritative sample indices")
    if value.get("decimal") != _fraction(expected)["decimal"]:
        raise ValueError("fraction decimal does not match authoritative value")
