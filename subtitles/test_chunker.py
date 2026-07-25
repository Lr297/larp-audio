from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Callable

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, SubtitleTimingProvenance
from larp_audio_mvp.core.errors import (
    ConfigurationError,
    SubtitleComplexityLimitError,
    SubtitleCoverageError,
)
from larp_audio_mvp.subtitles import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.display import subtitle_display_text
from larp_audio_mvp.subtitles.wrapping import (
    non_whitespace_signature,
    normalize_layout_whitespace,
    wrap_display_lines,
)


def _chunk(
    alignment: AlignmentResult, settings: SubtitleSettings | None = None
):
    return DeterministicSubtitleChunker().chunk(
        alignment,
        settings=settings or SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"alignment fixture").hexdigest(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Hello, WORLD!",
        "Привіт, світе!",
        "Українське слово й апостроф ’тут’.",
        "Slovenské ľščťžýáíé — presne.",
        "Don’t re-write state-of-the-art text.",
        "Emoji 😀 zostáva!",
        "Первый ряд.\r\nВторой ряд.",
    ],
)
def test_exact_text_unicode_and_punctuation_are_preserved(
    alignment_factory: Callable[..., AlignmentResult], text: str
) -> None:
    alignment = alignment_factory(text)
    document = _chunk(alignment)

    assert document.exact_script_text == text
    assert "".join(block.source_text_exact for block in document.blocks) == text
    assert tuple(block.display_text for block in document.blocks) == tuple(
        subtitle_display_text(block.source_text_exact)
        for block in document.blocks
    )
    assert tuple(
        index for block in document.blocks for index in block.script_word_indices
    ) == tuple(range(len(alignment.aligned_words)))


def test_asr_insertion_never_becomes_display_text_across_unsafe_line_anchor() -> None:
    from larp_audio_mvp.alignment import read_alignment

    alignment = read_alignment(
        __import__("pathlib").Path("examples/stage_8_1_example_alignment.json")
    )
    with pytest.raises(SubtitleCoverageError) as captured:
        _chunk(alignment)
    assert captured.value.code == "UNSAFE_UNRESOLVED_SUBTITLE_WORDS"
    assert "um" not in alignment.script.exact_text
    assert "uh" not in alignment.script.exact_text


@pytest.mark.parametrize("ending", [".", "?", "!"])
def test_punctuation_boundaries_are_stable(
    alignment_factory: Callable[..., AlignmentResult], ending: str
) -> None:
    text = f"One two{ending} Three four five six seven eight."
    alignment = alignment_factory(text)
    settings = SubtitleSettings()
    first = _chunk(alignment, settings)
    second = _chunk(alignment, settings)
    assert first == second
    assert len(first.blocks) >= 2
    assert first.blocks[0].source_text_exact.rstrip().endswith(ending)


@pytest.mark.parametrize("ending", [".", "?", "!", "...", "…"])
def test_normative_punctuation_is_a_hard_boundary(
    alignment_factory: Callable[..., AlignmentResult], ending: str
) -> None:
    text = f"One two{ending} Three four five."
    document = _chunk(alignment_factory(text))
    assert len(document.blocks) >= 2
    assert document.blocks[0].source_text_exact.rstrip().endswith(ending)


def test_original_newline_is_preferred_boundary(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory("One two three.\r\nFour five six.")
    document = _chunk(alignment)
    assert "".join(block.source_text_exact for block in document.blocks) == alignment.script.exact_text


def test_character_limit_and_semantic_ceiling_create_safe_blocks(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory("one two three four five six seven eight nine ten")
    by_words = _chunk(alignment)
    by_chars = _chunk(
        alignment,
        SubtitleSettings(max_characters_per_line=6),
    )
    assert all(block.word_count <= 10 for block in by_words.blocks)
    assert len(by_chars.blocks) > 1


def test_duration_reading_speed_and_gap_affect_segmentation(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = "spoken words need sensible semantic blocks now please"
    alignment = alignment_factory(
        text,
        word_starts=(100, 250, 400, 2_000, 2_150, 2_300, 2_450, 2_600),
        word_duration=100,
    )
    document = _chunk(
        alignment,
        SubtitleSettings(
            max_characters_per_second=50,
            preferred_gap_break_ms=500,
        ),
    )
    assert len(document.blocks) >= 2
    # Grammar cohesion outranks a pause: the verb/object pair remains intact
    # and the cut moves to the next safe edge.
    assert any("sensible semantic blocks" in block.display_text for block in document.blocks)
    assert document.blocks[0].cleaned_end_sample == 350
    assert document.diagnostics.verb_object_split_count == 0


def test_segmentation_limit_is_controlled(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory("one two three four")
    with pytest.raises(SubtitleComplexityLimitError) as captured:
        _chunk(alignment, SubtitleSettings(max_segmentation_cells=1))
    assert captured.value.code == "SUBTITLE_SEGMENTATION_LIMIT_EXCEEDED"


def test_leading_and_trailing_unresolved_words_are_attached(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory(
        "Before hello world After", missing_indices=(0, 3)
    )
    document = _chunk(alignment)
    assert document.diagnostics.attached_unresolved_words == 2
    assert document.blocks[0].contains_unresolved_words
    assert document.blocks[0].timing_provenance is (
        SubtitleTimingProvenance.ANCHORED_WITH_UNRESOLVED
    )


def test_middle_missing_word_keeps_interpolated_provenance(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory("hello missing world", missing_indices=(1,))
    document = _chunk(alignment)
    assert document.diagnostics.interpolated_script_words == 1
    containing = next(
        block for block in document.blocks if block.contains_interpolated_words
    )
    assert containing.timing_provenance in {
        SubtitleTimingProvenance.INTERPOLATED,
        SubtitleTimingProvenance.MIXED_OBSERVED_INTERPOLATED,
    }


def test_all_unresolved_and_excess_attachment_fail_safely(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    all_unresolved = alignment_factory("one two", missing_indices=(0, 1))
    with pytest.raises(SubtitleCoverageError) as captured:
        _chunk(all_unresolved)
    assert captured.value.code == "ALL_SUBTITLE_WORDS_UNRESOLVED"

    excessive = alignment_factory(
        "before one two three after",
        missing_indices=(0, 1, 2),
        max_interpolation_gap_ms=100,
    )
    with pytest.raises(SubtitleCoverageError):
        _chunk(excessive, SubtitleSettings(max_unresolved_words_per_block=1))


def test_low_timing_coverage_is_not_hidden(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory(
        "before one two three", missing_indices=(0, 1), max_interpolation_gap_ms=100
    )
    document = _chunk(
        alignment,
        SubtitleSettings(
            max_unresolved_words_per_block=2,
            minimum_timing_coverage_for_export="0.75",
        ),
    )
    assert document.diagnostics.timing_coverage == 1 / 2
    assert document.diagnostics.srt_exportable is False


def test_long_word_is_never_split_or_given_manual_layout_breaks(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    word = "supercalifragilisticexpialidocious"
    document = _chunk(
        alignment_factory(word),
        SubtitleSettings(max_characters_per_line=8),
    )
    assert word in document.blocks[0].display_lines
    assert document.blocks[0].display_lines == (word,)


@pytest.mark.parametrize(
    ("text", "expected_lines"),
    [
        ("short text", 1),
        ("balanced subtitle line wrapping", 2),
        ("hello , world", 1),
        ("Unicode žltý 😀 text", 2),
    ],
)
def test_line_wrapper_is_stable_and_preserving(
    text: str, expected_lines: int
) -> None:
    first, _ = wrap_display_lines(
        text, max_lines=2, max_characters_per_line=15
    )
    second, _ = wrap_display_lines(
        text, max_lines=2, max_characters_per_line=15
    )
    assert first == second
    assert len(first) == expected_lines
    assert non_whitespace_signature("\n".join(first)) == non_whitespace_signature(text)
    assert not any(line.startswith(",") for line in first)


def test_normalize_layout_changes_whitespace_only() -> None:
    source = "  Привіт,\r\n  world!  "
    display = normalize_layout_whitespace(source)
    assert display == "Привіт, world!"
    assert non_whitespace_signature(display) == non_whitespace_signature(source)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_lines": 0},
        {"max_words_per_block": True},
        {"max_unresolved_words_per_block": -1},
        {"max_characters_per_second": "NaN"},
        {"minimum_timing_coverage_for_export": "1.1"},
        {"allow_unresolved_attachment": 1},
    ],
)
def test_subtitle_configuration_invariants(overrides: dict[str, object]) -> None:
    with pytest.raises(ConfigurationError):
        SubtitleSettings(**overrides)  # type: ignore[arg-type]
