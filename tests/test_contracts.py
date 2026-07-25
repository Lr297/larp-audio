"""Construction smoke tests for the initial immutable contracts."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path, PurePosixPath

import pytest

from larp_audio_mvp.core.contracts import (
    ArtifactRecord,
    AudioInfo,
    EditKind,
    EditMap,
    EditSpan,
    InputProject,
    PauseSegment,
    ProcessingReport,
    ProcessingStatus,
    ProjectManifest,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
    SubtitleBlock,
    SubtitleTimingProvenance,
    WordTimestamp,
)


def test_required_contracts_can_be_created(tmp_path: Path) -> None:
    input_project = InputProject(
        project_id="project-001",
        audio_path=tmp_path / "voice.wav",
        script_text="Точный исходный текст.",
        output_directory=tmp_path / "output",
    )
    audio_info = AudioInfo(
        source_path=input_project.audio_path,
        sample_rate=48_000,
        channels=1,
        sample_format="s16",
        total_samples=96_000,
        sha256="source-hash",
    )
    word = WordTimestamp(
        recognized_text="точный",
        sample_range=SampleRange(1_000, 8_000),
        confidence=0.9,
    )
    edit_map = EditMap(
        schema_version="1",
        policy_version="test-policy",
        sample_rate=audio_info.sample_rate,
        source_total_samples=audio_info.total_samples,
        output_total_samples=audio_info.total_samples,
        source_sha256=audio_info.sha256 or "",
        spans=(
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(0, 96_000),
                output_range=SampleRange(0, 96_000),
                reason="identity",
            ),
        ),
    )
    subtitle = SubtitleBlock(
        block_index=1,
        source_char_start=0,
        source_char_end=len(input_project.script_text),
        source_text_exact=input_project.script_text,
        display_lines=(input_project.script_text,),
        first_token_index=0,
        last_token_index=5,
        script_word_indices=(0, 1, 2),
        interpolated_script_word_indices=(),
        unresolved_script_word_indices=(),
        cleaned_start_sample=1_000,
        cleaned_end_sample=90_000,
        original_start_sample=1_000,
        original_end_sample=90_000,
        duration_samples=89_000,
        word_count=3,
        visible_character_count=20,
        characters_per_second=Fraction(20 * 48_000, 89_000),
        timing_provenance=SubtitleTimingProvenance.OBSERVED,
        contains_interpolated_words=False,
        contains_unresolved_words=False,
    )
    report = ProcessingReport(
        schema_version="1",
        project_id=input_project.project_id,
        status=ProcessingStatus.PENDING,
        pipeline_version="0.1.0",
    )
    artifact = ArtifactRecord(
        relative_path=PurePosixPath("cleaned_audio.wav"),
        size_bytes=0,
        sha256="artifact-hash",
    )
    manifest = ProjectManifest(
        schema_version="1",
        project_id=input_project.project_id,
        pipeline_version="0.1.0",
        artifacts=(artifact,),
    )
    pause = PauseSegment(
        start_sample=24_000,
        end_sample=48_000,
        sample_rate=48_000,
    )
    recognized = RecognizedWord(
        text=" Точный",
        sample_rate=48_000,
        start_sample_cleaned=1_000,
        end_sample_cleaned=8_000,
        start_sample_original=1_500,
        end_sample_original=8_500,
        confidence=0.8,
    )
    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="ru",
        sample_rate=48_000,
        duration_samples_cleaned=96_000,
        duration_samples_original=100_000,
        words=(recognized,),
        metadata=(("backend_version", "test"),),
    )

    assert word.recognized_text == "точный"
    assert edit_map.output_total_samples == audio_info.total_samples
    assert subtitle.source_text_exact == input_project.script_text
    assert report.status is ProcessingStatus.PENDING
    assert manifest.artifacts == (artifact,)
    assert pause.length_samples == 24_000
    assert pause.start_seconds.numerator == 1
    assert pause.start_seconds.denominator == 2
    assert pause.end_seconds == 1
    assert pause.duration_seconds == pause.start_seconds
    assert recognized.start_seconds.numerator == 1
    assert recognized.start_seconds.denominator == 48
    assert recognition.duration == 2


def test_removed_span_has_no_fabricated_output_range() -> None:
    removed = EditSpan(
        kind=EditKind.REMOVE,
        source_range=SampleRange(10, 20),
        target_anchor=10,
        candidate_range=SampleRange(5, 25),
        retained_before_samples=5,
        retained_after_samples=5,
        reason="test-removal",
    )

    assert removed.output_range is None
    assert removed.target_start == removed.target_end == 10
    assert removed.removed_samples == 10


def test_pause_segment_rejects_invalid_sample_interval() -> None:
    with pytest.raises(ValueError):
        PauseSegment(start_sample=10, end_sample=10, sample_rate=48_000)
