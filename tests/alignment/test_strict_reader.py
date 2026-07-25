from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable

import pytest

from larp_audio_mvp.alignment import (
    ScriptAlignmentService,
    alignment_to_dict,
    read_alignment,
    read_script,
    write_alignment_atomic,
)
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import (
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
)
from larp_audio_mvp.core.errors import (
    AlignmentSerializationError,
    AlignmentValidationError,
)

ControlledError = (AlignmentSerializationError, AlignmentValidationError)


def _valid_payload(tmp_path: Path) -> dict[str, object]:
    script_path = tmp_path / "script.txt"
    script_path.write_bytes(b"Hello missing world")
    edit_map = EditMap(
        schema_version="1",
        policy_version="strict-v1",
        sample_rate=1_000,
        source_total_samples=2_000,
        output_total_samples=2_000,
        source_sha256="source-hash",
        output_sha256="cleaned-hash",
        spans=(
            EditSpan(
                EditKind.KEEP,
                SampleRange(0, 2_000),
                SampleRange(0, 2_000),
                reason="identity",
            ),
        ),
    )

    def word(text: str, start: int, end: int) -> RecognizedWord:
        return RecognizedWord(
            text=text,
            sample_rate=1_000,
            start_sample_cleaned=start,
            end_sample_cleaned=end,
            start_sample_original=start,
            end_sample_original=end,
            confidence=0.8,
        )

    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=1_000,
        duration_samples_cleaned=2_000,
        duration_samples_original=2_000,
        words=(
            word("Hello", 100, 200),
            word("um", 300, 350),
            word("uh", 400, 450),
            word("world", 1_000, 1_100),
        ),
        metadata=(("cleaned_audio_sha256", "cleaned-hash"),),
    )
    result = ScriptAlignmentService(AlignmentSettings()).align(
        read_script(script_path), recognition, edit_map
    )
    return alignment_to_dict(result)


def _write(payload: dict[str, object], path: Path) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _observation_as_diagnostic(payload: dict[str, object], index: int) -> dict[str, object]:
    recognition = payload["recognition"]
    assert isinstance(recognition, dict)
    words = recognition["words"]
    assert isinstance(words, list)
    word = words[index]
    assert isinstance(word, dict)
    return {
        "recognition_index": index,
        "text": word["text"],
        "cleaned_start_sample": word["start_sample_cleaned"],
        "cleaned_end_sample": word["end_sample_cleaned"],
        "original_start_sample": word["start_sample_original"],
        "original_end_sample": word["end_sample_original"],
        "confidence": word["confidence"],
    }


def _mutate_denominator_zero(payload: dict[str, object]) -> None:
    payload["diagnostics"]["text_alignment_coverage"]["denominator"] = 0  # type: ignore[index]


def _mutate_denominator_negative(payload: dict[str, object]) -> None:
    payload["diagnostics"]["text_alignment_coverage"]["denominator"] = -1  # type: ignore[index]


def _mutate_numerator_string(payload: dict[str, object]) -> None:
    payload["diagnostics"]["text_alignment_coverage"]["numerator"] = "3"  # type: ignore[index]


def _mutate_exact_matches(payload: dict[str, object]) -> None:
    payload["diagnostics"]["exact_matches"] = 999  # type: ignore[index]


def _mutate_coverage(payload: dict[str, object]) -> None:
    payload["diagnostics"]["text_alignment_coverage"] = {  # type: ignore[index]
        "numerator": 0,
        "denominator": 1,
        "decimal": "0",
    }


def _mutate_decimal_nan(payload: dict[str, object]) -> None:
    payload["diagnostics"]["text_alignment_coverage"]["decimal"] = "NaN"  # type: ignore[index]


def _mutate_decimal_infinity(payload: dict[str, object]) -> None:
    payload["diagnostics"]["text_alignment_coverage"]["decimal"] = "Infinity"  # type: ignore[index]


def _mutate_script_total(payload: dict[str, object]) -> None:
    payload["diagnostics"]["total_script_words"] = 999  # type: ignore[index]


def _mutate_asr_total(payload: dict[str, object]) -> None:
    payload["diagnostics"]["total_asr_words"] = 999  # type: ignore[index]


def _mutate_duplicate_matched(payload: dict[str, object]) -> None:
    payload["aligned_words"][0]["matched_recognition_indices"] = [0, 0]  # type: ignore[index]


def _mutate_matched_and_unmatched(payload: dict[str, object]) -> None:
    payload["unmatched_asr_words"].append(_observation_as_diagnostic(payload, 0))  # type: ignore[union-attr]


def _mutate_rejected_and_unmatched(payload: dict[str, object]) -> None:
    rejected = payload["rejected_asr_evidence"]
    assert isinstance(rejected, list)
    item = dict(rejected[0])
    for key in (
        "rejection_reason",
        "related_script_word_indices",
        "attempted_match_type",
        "attempted_operation_id",
    ):
        item.pop(key)
    payload["unmatched_asr_words"].append(item)  # type: ignore[union-attr]


def _mutate_matched_and_rejected(payload: dict[str, object]) -> None:
    rejected = payload["rejected_asr_evidence"]
    assert isinstance(rejected, list)
    rejected[0] = {
        **rejected[0],
        **_observation_as_diagnostic(payload, 0),
        "rejection_reason": "substitution_not_accepted",
        "related_script_word_indices": [1],
        "attempted_match_type": "substitution",
        "attempted_operation_id": "alignment-op-000001",
    }


def _mutate_lost_index(payload: dict[str, object]) -> None:
    payload["unmatched_asr_words"] = []


def _mutate_unknown_index(payload: dict[str, object]) -> None:
    payload["unmatched_asr_words"][0]["recognition_index"] = 999  # type: ignore[index]


def _mutate_reused_index(payload: dict[str, object]) -> None:
    first = payload["aligned_words"][0]  # type: ignore[index]
    last = payload["aligned_words"][2]  # type: ignore[index]
    last["matched_recognition_indices"] = [0]
    last["cleaned_start_sample"] = first["cleaned_start_sample"]
    last["cleaned_end_sample"] = first["cleaned_end_sample"]
    last["original_start_sample"] = first["original_start_sample"]
    last["original_end_sample"] = first["original_end_sample"]


def _mutate_interpolated_matched(payload: dict[str, object]) -> None:
    payload["aligned_words"][1]["matched_recognition_indices"] = [1]  # type: ignore[index]


def _mutate_interpolated_confidence(payload: dict[str, object]) -> None:
    payload["aligned_words"][1]["asr_confidence"] = 0.5  # type: ignore[index]


def _mutate_observed_without_index(payload: dict[str, object]) -> None:
    payload["aligned_words"][0]["matched_recognition_indices"] = []  # type: ignore[index]


def _mutate_unresolved_with_timing(payload: dict[str, object]) -> None:
    payload["aligned_words"][1]["timing_status"] = "unresolved"  # type: ignore[index]
    payload["aligned_words"][1]["match_type"] = "unresolved"  # type: ignore[index]


def _mutate_word_exact_text(payload: dict[str, object]) -> None:
    payload["aligned_words"][0]["exact_text"] = "HELLO"  # type: ignore[index]


def _mutate_char_gap(payload: dict[str, object]) -> None:
    payload["tokens"][1]["char_start"] += 1  # type: ignore[index]


def _mutate_token_reconstruction(payload: dict[str, object]) -> None:
    payload["tokens"][0]["exact_text"] = "Hallo"  # type: ignore[index]


def _mutate_empty_script(payload: dict[str, object]) -> None:
    payload["script"]["exact_text"] = ""  # type: ignore[index]


def _mutate_whitespace_script(payload: dict[str, object]) -> None:
    payload["script"]["exact_text"] = "   "  # type: ignore[index]
    payload["script"]["character_count"] = 3  # type: ignore[index]


def _mutate_schema(payload: dict[str, object]) -> None:
    payload["schema_version"] = "1"


def _mutate_match_timing(payload: dict[str, object]) -> None:
    payload["aligned_words"][0]["timing_status"] = "interpolated"  # type: ignore[index]


def _mutate_out_of_range(payload: dict[str, object]) -> None:
    payload["aligned_words"][2]["cleaned_end_sample"] = 9_999  # type: ignore[index]


def _mutate_timeline_mapping(payload: dict[str, object]) -> None:
    payload["aligned_words"][2]["original_end_sample"] += 1  # type: ignore[index]


MUTATIONS: tuple[tuple[str, Callable[[dict[str, object]], None]], ...] = (
    ("denominator_zero", _mutate_denominator_zero),
    ("denominator_negative", _mutate_denominator_negative),
    ("numerator_string", _mutate_numerator_string),
    ("fake_exact_matches", _mutate_exact_matches),
    ("fake_coverage", _mutate_coverage),
    ("decimal_nan", _mutate_decimal_nan),
    ("decimal_infinity", _mutate_decimal_infinity),
    ("fake_script_total", _mutate_script_total),
    ("fake_asr_total", _mutate_asr_total),
    ("duplicate_matched", _mutate_duplicate_matched),
    ("matched_and_unmatched", _mutate_matched_and_unmatched),
    ("rejected_and_unmatched", _mutate_rejected_and_unmatched),
    ("matched_and_rejected", _mutate_matched_and_rejected),
    ("lost_index", _mutate_lost_index),
    ("unknown_index", _mutate_unknown_index),
    ("reused_index", _mutate_reused_index),
    ("interpolated_matched", _mutate_interpolated_matched),
    ("interpolated_confidence", _mutate_interpolated_confidence),
    ("observed_without_index", _mutate_observed_without_index),
    ("unresolved_with_timing", _mutate_unresolved_with_timing),
    ("word_exact_text", _mutate_word_exact_text),
    ("char_gap", _mutate_char_gap),
    ("token_reconstruction", _mutate_token_reconstruction),
    ("empty_script", _mutate_empty_script),
    ("whitespace_script", _mutate_whitespace_script),
    ("schema", _mutate_schema),
    ("match_timing", _mutate_match_timing),
    ("out_of_range", _mutate_out_of_range),
    ("timeline_mapping", _mutate_timeline_mapping),
)


@pytest.mark.parametrize(("name", "mutation"), MUTATIONS, ids=[item[0] for item in MUTATIONS])
def test_strict_reader_rejects_corruption_without_raw_exception(
    tmp_path: Path,
    name: str,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    payload = copy.deepcopy(_valid_payload(tmp_path))
    mutation(payload)
    destination = tmp_path / f"{name}.json"
    _write(payload, destination)

    with pytest.raises(ControlledError):
        read_alignment(destination)


def test_strict_reader_accepts_valid_result_and_writer_is_deterministic(
    tmp_path: Path,
) -> None:
    payload = _valid_payload(tmp_path)
    source = tmp_path / "source.json"
    _write(payload, source)
    result = read_alignment(source)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_alignment_atomic(result, first)
    write_alignment_atomic(result, second)
    assert first.read_bytes() == second.read_bytes()
    assert read_alignment(first) == result
