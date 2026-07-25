from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from larp_audio_mvp.alignment import (
    ScriptAlignmentService,
    alignment_to_dict,
    read_alignment,
    read_script,
    write_alignment_atomic,
)
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import (
    AlignmentMatchType,
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
    TimingStatus,
)
from larp_audio_mvp.core.errors import (
    AlignmentSerializationError,
    AlignmentValidationError,
    RecognitionCompatibilityError,
)
from larp_audio_mvp.models.serialization import read_recognition, write_recognition_atomic


def _edit_map() -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="test-v1",
        sample_rate=1_000,
        source_total_samples=12_000,
        output_total_samples=10_000,
        source_sha256="source-hash",
        output_sha256="cleaned-hash",
        spans=(
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(0, 4_000),
                output_range=SampleRange(0, 4_000),
                reason="keep",
            ),
            EditSpan(
                kind=EditKind.REMOVE,
                source_range=SampleRange(4_000, 6_000),
                target_anchor=4_000,
                candidate_range=SampleRange(3_500, 6_500),
                retained_before_samples=500,
                retained_after_samples=500,
                reason="pause",
            ),
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(6_000, 12_000),
                output_range=SampleRange(4_000, 10_000),
                reason="keep",
            ),
        ),
    )


def _word(text: str, start: int, end: int, confidence: float | None = None) -> RecognizedWord:
    original_start = start if start < 4_000 else start + 2_000
    original_end = end if end < 4_000 else end + 2_000
    if end == 4_000:
        original_end = 6_000
    return RecognizedWord(
        text=text,
        sample_rate=1_000,
        start_sample_cleaned=start,
        end_sample_cleaned=end,
        start_sample_original=original_start,
        end_sample_original=original_end,
        confidence=confidence,
    )


def _recognition(*words: RecognizedWord) -> RecognitionResult:
    return RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=1_000,
        duration_samples_cleaned=10_000,
        duration_samples_original=12_000,
        words=words,
        metadata=(("cleaned_audio_sha256", "cleaned-hash"),),
    )


def _document(tmp_path: Path, text: str = "Hello brave new world"):
    source = tmp_path / "original script.txt"
    source.write_bytes(text.encode("utf-8"))
    return read_script(source), source.read_bytes()


def test_assigns_observed_and_interpolated_dual_timeline_samples(tmp_path: Path) -> None:
    document, original_bytes = _document(tmp_path)
    recognition = _recognition(
        _word("Hello", 500, 1_500, 0.9),
        _word("brave", 2_000, 3_000, None),
        _word("world", 4_000, 5_000, 0.8),
    )

    result = ScriptAlignmentService(AlignmentSettings()).align(
        document, recognition, _edit_map()
    )

    assert [word.exact_text for word in result.aligned_words] == [
        "Hello", "brave", "new", "world"
    ]
    interpolated = result.aligned_words[2]
    assert interpolated.match_type is AlignmentMatchType.INTERPOLATED
    assert interpolated.timing_status is TimingStatus.INTERPOLATED
    assert (interpolated.cleaned_start_sample, interpolated.cleaned_end_sample) == (3_000, 4_000)
    assert (interpolated.original_start_sample, interpolated.original_end_sample) == (3_000, 6_000)
    assert interpolated.asr_confidence is None
    assert result.aligned_words[3].original_start_sample == 6_000
    assert result.diagnostics.observed_timing_coverage.numerator == 3
    assert result.diagnostics.total_timing_coverage == 1
    assert document.source_path.read_bytes() == original_bytes


def test_leading_and_trailing_words_are_not_extrapolated(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "Before hello after")
    result = ScriptAlignmentService(AlignmentSettings()).align(
        document, _recognition(_word("hello", 2_000, 3_000)), _edit_map()
    )
    assert result.aligned_words[0].timing_status is TimingStatus.UNRESOLVED
    assert result.aligned_words[2].timing_status is TimingStatus.UNRESOLVED
    assert result.aligned_words[0].cleaned_start_sample is None
    assert result.aligned_words[2].cleaned_start_sample is None


def test_interpolation_respects_gap_limit(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "hello missing world")
    result = ScriptAlignmentService(
        AlignmentSettings(max_interpolation_gap_ms=500)
    ).align(
        document,
        _recognition(_word("hello", 500, 1_000), _word("world", 4_000, 5_000)),
        _edit_map(),
    )
    assert result.aligned_words[1].timing_status is TimingStatus.UNRESOLVED


def test_many_script_to_one_distributes_all_integer_samples(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "new york")
    result = ScriptAlignmentService(AlignmentSettings()).align(
        document, _recognition(_word("newyork", 100, 105, 0.7)), _edit_map()
    )
    first, second = result.aligned_words
    assert first.match_type is AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR
    assert first.timing_status is TimingStatus.DISTRIBUTED
    assert (first.cleaned_start_sample, first.cleaned_end_sample) == (100, 103)
    assert (second.cleaned_start_sample, second.cleaned_end_sample) == (103, 105)
    assert second.cleaned_end_sample - first.cleaned_start_sample == 5


def test_asr_insertion_is_diagnostic_only_and_not_script_text(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "hello world")
    result = ScriptAlignmentService(AlignmentSettings()).align(
        document,
        _recognition(
            _word("hello", 100, 500),
            _word("um", 600, 700),
            _word("world", 800, 1_200),
        ),
        _edit_map(),
    )
    assert [word.exact_text for word in result.aligned_words] == ["hello", "world"]
    assert [word.text for word in result.unmatched_asr_words] == ["um"]
    assert result.unmatched_asr_words[0].recognition_index == 1


def test_result_serialization_roundtrip_is_stable_atomic_and_unicode(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "Привіт, world!\r\n")
    result = ScriptAlignmentService(AlignmentSettings()).align(
        document,
        _recognition(_word("привіт", 100, 500), _word("world", 600, 1_000)),
        _edit_map(),
    )
    destination = tmp_path / "alignment ü.json"

    write_alignment_atomic(result, destination)
    first = destination.read_bytes()
    restored = read_alignment(destination)
    write_alignment_atomic(restored, destination)

    assert destination.read_bytes() == first
    assert alignment_to_dict(restored) == alignment_to_dict(result)
    assert json.loads(first)["script"]["exact_text"] == document.exact_text
    assert first.endswith(b"\n")
    assert list(tmp_path.glob("*.partial.json")) == []


def test_atomic_writer_cleans_partial_after_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document, _ = _document(tmp_path, "hello")
    result = ScriptAlignmentService(AlignmentSettings()).align(
        document, _recognition(_word("hello", 100, 500)), _edit_map()
    )
    import larp_audio_mvp.alignment.serialization as module

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("artificial failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(AlignmentSerializationError):
        write_alignment_atomic(result, tmp_path / "alignment.json")
    assert not (tmp_path / "alignment.json").exists()
    assert list(tmp_path.glob("*.partial.json")) == []


def test_rejects_recognition_edit_map_incompatibility(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "hello")
    incompatible = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=2_000,
        duration_samples_cleaned=10_000,
        duration_samples_original=12_000,
        words=(),
    )
    with pytest.raises(AlignmentValidationError) as captured:
        ScriptAlignmentService(AlignmentSettings()).align(document, incompatible, _edit_map())
    assert captured.value.code == "SAMPLE_RATE_MISMATCH"


def test_recognition_reader_rejects_tampered_derived_seconds(tmp_path: Path) -> None:
    source = tmp_path / "recognition.json"
    write_recognition_atomic(_recognition(_word("hello", 100, 500)), source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["words"][0]["start_seconds"]["numerator"] += 1
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RecognitionCompatibilityError) as captured:
        read_recognition(source)
    assert captured.value.code == "INVALID_RECOGNITION"


def test_repeated_runs_return_identical_result(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, "hello brave world")
    recognition = _recognition(_word("hello", 100, 500), _word("world", 900, 1_200))
    service = ScriptAlignmentService(AlignmentSettings())
    first = service.align(document, recognition, _edit_map())
    second = service.align(document, recognition, _edit_map())
    assert alignment_to_dict(first) == alignment_to_dict(second)
