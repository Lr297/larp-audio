from __future__ import annotations

from pathlib import Path

from larp_audio_mvp.alignment import ScriptAlignmentService, read_script
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import (
    AlignedScriptWord,
    AlignedWord,
    AlignmentMatchType,
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
    TimingStatus,
)


def _identity_map() -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="provenance-test-v1",
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


def _word(text: str, start: int, end: int) -> RecognizedWord:
    return RecognizedWord(
        text=text,
        sample_rate=1_000,
        start_sample_cleaned=start,
        end_sample_cleaned=end,
        start_sample_original=start,
        end_sample_original=end,
        confidence=0.8,
    )


def _recognition(*words: RecognizedWord) -> RecognitionResult:
    return RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=1_000,
        duration_samples_cleaned=2_000,
        duration_samples_original=2_000,
        words=words,
        metadata=(("cleaned_audio_sha256", "cleaned-hash"),),
    )


def _script(tmp_path: Path, text: str):
    path = tmp_path / "script.txt"
    path.write_bytes(text.encode("utf-8"))
    return read_script(path)


def test_substitution_then_interpolation_does_not_lose_asr_observation(
    tmp_path: Path,
) -> None:
    result = ScriptAlignmentService(AlignmentSettings()).align(
        _script(tmp_path, "Hello missing world"),
        _recognition(
            _word("Hello", 100, 200),
            _word("um", 300, 350),
            _word("uh", 400, 450),
            _word("world", 1_000, 1_100),
        ),
        _identity_map(),
    )

    hello, missing, world = result.aligned_words
    assert hello.match_type is AlignmentMatchType.EXACT
    assert world.match_type is AlignmentMatchType.EXACT
    assert missing.match_type is AlignmentMatchType.INTERPOLATED
    assert missing.timing_status is TimingStatus.INTERPOLATED
    assert missing.matched_recognition_indices == ()
    assert missing.alignment_operation_id is None
    assert missing.asr_confidence is None
    assert missing.text_similarity is None
    assert missing.interpolation_left_anchor_script_word_index == 0
    assert missing.interpolation_right_anchor_script_word_index == 2

    rejected = {item.recognition_index: item for item in result.rejected_asr_evidence}
    unmatched = {item.recognition_index: item for item in result.unmatched_asr_words}
    assert len(rejected) == 1
    assert len(unmatched) == 1
    assert {item.text for item in rejected.values()} | {
        item.text for item in unmatched.values()
    } == {"um", "uh"}
    rejected_item = next(iter(rejected.values()))
    assert rejected_item.rejection_reason == "substitution_not_accepted"
    assert rejected_item.related_script_word_indices == (1,)
    assert rejected_item.attempted_match_type is AlignmentMatchType.SUBSTITUTION

    accepted = {
        index
        for aligned in result.aligned_words
        for index in aligned.matched_recognition_indices
    }
    assert accepted | set(unmatched) | set(rejected) == {0, 1, 2, 3}
    assert not accepted & set(unmatched)
    assert not accepted & set(rejected)
    assert not set(unmatched) & set(rejected)
    assert result.diagnostics.classified_asr_words == 4
    assert result.diagnostics.provenance_complete is True


def test_rejected_many_to_one_keeps_evidence_and_avoids_false_match(
    tmp_path: Path,
) -> None:
    result = ScriptAlignmentService(AlignmentSettings()).align(
        _script(tmp_path, "before new york after"),
        _recognition(
            _word("before", 100, 200),
            _word("newyork", 300, 301),
            _word("after", 500, 600),
        ),
        _identity_map(),
    )

    new, york = result.aligned_words[1:3]
    assert new.match_type is AlignmentMatchType.INTERPOLATED
    assert york.match_type is AlignmentMatchType.INTERPOLATED
    assert new.matched_recognition_indices == york.matched_recognition_indices == ()
    assert new.asr_confidence is york.asr_confidence is None
    assert len(result.rejected_asr_evidence) == 1
    evidence = result.rejected_asr_evidence[0]
    assert evidence.recognition_index == 1
    assert evidence.text == "newyork"
    assert evidence.rejection_reason == "timing_distribution_impossible"
    assert evidence.related_script_word_indices == (1, 2)
    assert evidence.attempted_match_type is AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR
    assert result.diagnostics.provenance_complete is True


def test_valid_many_to_one_uses_one_group_identifier(tmp_path: Path) -> None:
    result = ScriptAlignmentService(AlignmentSettings()).align(
        _script(tmp_path, "new york"),
        _recognition(_word("newyork", 100, 105)),
        _identity_map(),
    )
    first, second = result.aligned_words
    assert first.alignment_operation_id == second.alignment_operation_id
    assert first.alignment_operation_id is not None
    assert first.matched_recognition_indices == second.matched_recognition_indices == (0,)
    assert first.cleaned_end_sample == second.cleaned_start_sample
    assert result.diagnostics.provenance_complete is True


def test_aligned_word_is_only_a_deprecated_alias() -> None:
    assert AlignedWord is AlignedScriptWord
