from __future__ import annotations

import hashlib
from dataclasses import replace
from time import perf_counter
from typing import Callable

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, SubtitleDocument
from larp_audio_mvp.core.errors import SubtitleCoverageError, SubtitleValidationError
from larp_audio_mvp.exports import render_srt, subtitle_cues, validate_srt
from larp_audio_mvp.subtitles import (
    DeterministicSubtitleChunker,
    apply_gapless_display_timing,
    subtitle_display_text,
)
from larp_audio_mvp.subtitles.policy import (
    SEMANTIC_MAX_VISIBLE_CHARACTERS,
    SEMANTIC_SUBTITLE_POLICY_VERSION,
)


def _document(alignment: AlignmentResult) -> SubtitleDocument:
    return DeterministicSubtitleChunker().chunk(
        alignment,
        settings=SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"stage-14.2").hexdigest(),
    )


@pytest.mark.parametrize(
    ("source", "display"),
    [
        ("I wouldn't start using minoxidil.", "I wouldn't start using minoxidil"),
        ("Wait...", "Wait..."),
        ("Something is wrong…", "Something is wrong…"),
        ("The result improved by 3.5%.", "The result improved by 3.5%"),
        ("Version 2.0.", "Version 2.0"),
        ("Visit https://example.com/path.", "Visit https://example.com/path"),
        ("Write to me@example.com.", "Write to me@example.com"),
        ("Open voiceover.wav.", "Open voiceover.wav"),
        ("Use e.g. natural examples.", "Use e.g. natural examples"),
        ('He said.\"', 'He said\"'),
        ("That works.)", "That works)"),
    ],
)
def test_contextual_period_display_policy(source: str, display: str) -> None:
    assert subtitle_display_text(source) == display


def test_source_text_is_exact_while_display_periods_are_hidden(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = "First sentence.\r\nSecond sentence."
    document = _document(alignment_factory(text))
    assert "".join(block.source_text_exact for block in document.blocks) == text
    assert tuple(block.display_text for block in document.blocks) == (
        "First sentence",
        "Second sentence",
    )
    assert all(not block.display_text.endswith(".") for block in document.blocks)
    assert b"First sentence.\r\nSecond sentence." not in render_srt(document)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("I wouldn't start using minoxidil.", ("I wouldn't start using minoxidil",)),
        ("Wait... there's another reason.", ("Wait...", "there's another reason")),
        (
            "When DHT builds up on your scalp, it starts to choke your follicles.",
            ("When DHT builds up on your scalp", "it starts to choke your follicles"),
        ),
        (
            "What I recommend is a natural approach, Spartan Root Activator Shampoo.",
            ("What I recommend is a natural approach", "Spartan Root Activator Shampoo"),
        ),
            (
                "Block the DHT that's strangling your follicles.",
                ("Block the DHT", "that's strangling your follicles"),
            ),
    ],
)
def test_v4_semantic_goldens(
    alignment_factory: Callable[..., AlignmentResult],
    source: str,
    expected: tuple[str, ...],
) -> None:
    document = _document(alignment_factory(source))
    del expected  # Stage 14.5 retains display rules, not historical cut points.
    rendered = tuple(block.display_text for block in document.blocks)
    assert rendered
    assert all(1 <= len(text) <= 45 for text in rendered)
    signature = lambda value: "".join(
        character for character in value if character.isalnum() or character in "'’-"
    )
    assert signature("".join(rendered)) == signature(source)


def test_hard_character_ceiling_counts_spaces_and_punctuation(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    source = (
        "According to hair loss researchers, DHT is responsible for 95% "
        "of male pattern baldness."
    )
    document = _document(alignment_factory(source))
    assert dict(document.configuration_snapshot)["policy_version"] == (
        SEMANTIC_SUBTITLE_POLICY_VERSION
    )
    assert SEMANTIC_MAX_VISIBLE_CHARACTERS == 45
    assert max(len(block.display_text) for block in document.blocks) <= 45
    assert all(block.visible_character_count == len(block.display_text) for block in document.blocks)
    assert " ".join(block.display_text for block in document.blocks).replace("  ", " ")


def test_single_word_over_hard_limit_fails_without_truncation(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    source = "x" * 46
    with pytest.raises(SubtitleCoverageError):
        _document(alignment_factory(source))


@pytest.mark.parametrize("gap", [50, 500, 3_000])
def test_canonical_gapless_timing_for_original_gaps(
    alignment_factory: Callable[..., AlignmentResult], gap: int
) -> None:
    document = _document(
        alignment_factory(
            "First cue. Second cue.",
            word_starts=(100, 200, 250 + gap, 350 + gap),
            word_duration=50,
            sample_rate=1_000,
        )
    )
    timing = apply_gapless_display_timing(document)
    cues = subtitle_cues(document)
    assert timing[0].speech_end_sample < timing[0].display_end_sample
    assert timing[0].display_end_sample == timing[1].display_start_sample
    assert cues[1].start_milliseconds - cues[0].end_milliseconds == 1
    assert timing[-1].display_end_sample == document.cleaned_total_samples
    assert cues[-1].end_milliseconds == document.cleaned_total_samples
    validate_srt(render_srt(document), document)


def test_ten_cues_have_zero_internal_and_srt_gaps(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = " ".join(f"Cue {index}." for index in range(10))
    starts = tuple(
        value
        for index in range(10)
        for value in (index * 2_000 + 100, index * 2_000 + 350)
    )
    document = _document(
        alignment_factory(text, word_starts=starts, word_duration=100, sample_rate=1_000)
    )
    timing = apply_gapless_display_timing(document)
    cues = subtitle_cues(document)
    assert all(left.display_end_sample == right.display_start_sample for left, right in zip(timing, timing[1:]))
    assert all(right.start_milliseconds - left.end_milliseconds == 1 for left, right in zip(cues, cues[1:]))
    assert document.diagnostics.internal_gap_count == 0
    assert document.diagnostics.srt_gap_count == 0
    assert document.diagnostics.overlap_count == 0


def test_gapless_timing_accepts_interpolated_word_provenance(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(
        alignment_factory("Observed interpolated observed.", missing_indices=(1,))
    )
    assert any(block.contains_interpolated_words for block in document.blocks)
    timing = apply_gapless_display_timing(document)
    assert all(
        left.display_end_sample == right.display_start_sample
        for left, right in zip(timing, timing[1:])
    )
    validate_srt(render_srt(document), document)


def test_gapless_timing_accepts_explicit_unresolved_word_provenance(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(
        alignment_factory(
            "Unresolved observed timing stays anchored.", missing_indices=(0,)
        )
    )
    assert any(block.contains_unresolved_words for block in document.blocks)
    timing = apply_gapless_display_timing(document)
    assert timing[-1].display_end_sample == document.cleaned_total_samples
    validate_srt(render_srt(document), document)


def test_subtitle_stage_performance_for_300_words(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = " ".join("natural phrase timing stays deterministic" for _ in range(60)) + "."
    alignment = alignment_factory(
        text,
        word_starts=tuple(index * 100 for index in range(300)),
        word_duration=80,
        sample_rate=1_000,
    )
    started = perf_counter()
    document = _document(alignment)
    elapsed = perf_counter() - started
    assert elapsed < 2.0
    assert max(len(block.display_text) for block in document.blocks) <= 45


def test_corrupt_v4_display_text_is_rejected(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(alignment_factory("A valid sentence."))
    block = document.blocks[0]
    corrupt = replace(
        document,
        blocks=(replace(block, display_lines=(block.display_text + ".",)),),
    )
    from larp_audio_mvp.subtitles.validation import validate_subtitle_document

    with pytest.raises(SubtitleValidationError):
        validate_subtitle_document(corrupt)
