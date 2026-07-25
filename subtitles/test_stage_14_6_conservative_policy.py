from __future__ import annotations

from collections.abc import Callable

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, SubtitleDocument
from larp_audio_mvp.subtitles.chunker import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.policy import (
    BoundaryPriority,
    boundary_priority,
    semantic_boundary_signals,
    word_keys,
)


def _chunk(
    alignment_factory: Callable[..., AlignmentResult], text: str
) -> SubtitleDocument:
    return DeterministicSubtitleChunker().chunk(
        alignment_factory(text, word_duration=350),
        settings=SubtitleSettings(),
        source_alignment_sha256="6" * 64,
    )


def _cues(document: SubtitleDocument) -> tuple[str, ...]:
    return tuple(block.display_text_plain for block in document.blocks)


def _assert_zero_conservative_violations(document: SubtitleDocument) -> None:
    for name in (
        "unnecessary_split_count",
        "required_boundary_miss_count",
        "list_item_merge_violation_count",
        "list_item_internal_split_count",
        "protected_unit_violation_count",
        "incomplete_ending_count",
        "orphan_beginning_count",
        "wh_clause_split_count",
        "or_not_split_count",
        "parser_low_confidence_split_count",
    ):
        assert getattr(document.diagnostics, name) == 0, name
    assert document.diagnostics.maximum_display_characters <= 45


@pytest.mark.parametrize(
    "text",
    (
        "Full or not I make it",
        "Ready or not we have to begin",
        "Working or not the system stays available",
        "Here's what keeps me in business",
        "This is what keeps the system running",
        "That's what causes the problem",
        "Pills can hush my alarms for a while",
    ),
)
def test_compact_natural_phrase_uses_one_semantic_cue(
    alignment_factory: Callable[..., AlignmentResult], text: str
) -> None:
    document = _chunk(alignment_factory, text)
    assert _cues(document) == (text,)
    assert len(document.blocks[0].display_lines) <= 2
    _assert_zero_conservative_violations(document)


def test_reported_repeated_preposition_list_has_complete_items(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _chunk(
        alignment_factory,
        "Women point the finger at age, at childbirth, at weak pelvic floors",
    )
    assert _cues(document) == (
        "Women point the finger",
        "at age",
        "at childbirth",
        "at weak pelvic floors",
    )
    assert document.diagnostics.list_item_merge_violation_count == 0
    assert document.diagnostics.protected_unit_violation_count == 0
    assert document.diagnostics.trailing_comma_violation_count == 0
    _assert_zero_conservative_violations(document)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        (
            "Patients blame stress, poor sleep, and weak muscles",
            ("Patients blame", "stress", "poor sleep", "and weak muscles"),
        ),
        (
            "The changes happen at work, at home, and during exercise",
            (
                "The changes happen",
                "at work",
                "at home",
                "and during exercise",
            ),
        ),
        (
            "at home, at work, at school",
            ("at home", "at work", "at school"),
        ),
        (
            "after lunch, after exercise, after sleep",
            ("after lunch", "after exercise", "after sleep"),
        ),
        (
            "with pain, with pressure, with discomfort",
            ("with pain", "with pressure", "with discomfort"),
        ),
    ),
)
def test_unseen_parallel_lists_are_isolated(
    alignment_factory: Callable[..., AlignmentResult],
    text: str,
    expected: tuple[str, ...],
) -> None:
    document = _chunk(alignment_factory, text)
    assert _cues(document) == expected
    _assert_zero_conservative_violations(document)


@pytest.mark.parametrize(
    "text",
    (
        "If this happens, call your doctor",
        "Now listen, this is important",
        "Full or not I make it",
    ),
)
def test_single_comma_is_not_a_list(
    alignment_factory: Callable[..., AlignmentResult], text: str
) -> None:
    document = _chunk(alignment_factory, text)
    assert document.diagnostics.list_item_count == 0


def test_or_not_and_wh_boundaries_are_parser_guardrails(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    for text, forbidden_after in (
        ("Ready or not we have to begin", ("Ready", "or")),
        ("Here's what keeps the system running", ("what",)),
    ):
        alignment = alignment_factory(text)
        signals = semantic_boundary_signals(
            text, alignment.aligned_words, word_keys(alignment.aligned_words)
        )
        words = tuple(word.exact_text for word in alignment.aligned_words)
        for value in forbidden_after:
            position = words.index(value) + 1
            assert boundary_priority(position, signals) is BoundaryPriority.FORBIDDEN


def test_two_line_layout_does_not_create_another_timed_cue(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = "Here's what keeps this business running"
    document = _chunk(alignment_factory, text)
    assert len(text) <= 45
    assert len(document.blocks) == 1
    assert len(document.blocks[0].display_lines) <= 2
    assert document.blocks[0].display_text_plain == text


def test_conservative_policy_is_deterministic(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = "Whether it works or not we need an answer"
    first = _chunk(alignment_factory, text)
    second = _chunk(alignment_factory, text)
    assert _cues(first) == _cues(second)
    assert _cues(first) == (text,)


# ---------------------------------------------------------------------------
# Stage-14-7 runtime-path regression: conj-dependency list detection
# ---------------------------------------------------------------------------
# These tests exercise the live spaCy path.  The alignment_factory creates
# real AlignmentResult objects via ScriptAlignmentService so char_start /
# char_end offsets match what the packaged application produces.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "min_items"),
    (
        # Repeated preposition with one comma + "and" (X, Y and Z)
        ("She pointed at anger, at grief and at fear", 2),
        # Repeated preposition: two commas, no "and" (already passes)
        ("She sat at home, at work, at school", 3),
        # Repeated preposition, "and" only, no commas
        ("They looked at him and at her and at us", 1),
    ),
)
def test_repeated_preposition_lists_are_split(
    alignment_factory,
    text: str,
    min_items: int,
) -> None:
    """Repeated-preposition lists produce at least min_items semantic cues."""
    document = _chunk(alignment_factory, text)
    assert len(document.blocks) >= min_items, (
        f"Expected >= {min_items} cues for {text!r}, got {_cues(document)}"
    )
    assert document.diagnostics.list_item_merge_violation_count == 0
    assert document.diagnostics.maximum_display_characters <= 45


@pytest.mark.parametrize(
    ("text", "min_items"),
    (
        # Comma-and list: X, Y, and Z
        ("We ate bread, cheese, and fruit", 3),
        # Coordination chain: X and Y and Z
        ("We saw cats and dogs and birds", 1),
        # Parallel NPs with oxford comma
        ("She brought a pen, a notebook, and an eraser", 3),
    ),
)
def test_comma_and_coordination_lists_are_split(
    alignment_factory,
    text: str,
    min_items: int,
) -> None:
    """Comma-plus-and and chained-and lists produce >= min_items cues."""
    document = _chunk(alignment_factory, text)
    assert len(document.blocks) >= min_items, (
        f"Expected >= {min_items} cues for {text!r}, got {_cues(document)}"
    )
    assert document.diagnostics.maximum_display_characters <= 45


@pytest.mark.parametrize(
    "text",
    (
        # Single introductory comma, no parallel structure
        "If this happens, call your doctor",
        "Now listen, this is important",
        "Full or not I make it",
    ),
)
def test_non_list_commas_produce_no_list_items(
    alignment_factory,
    text: str,
) -> None:
    """Sentences without genuine enumeration have list_item_count == 0."""
    document = _chunk(alignment_factory, text)
    assert document.diagnostics.list_item_count == 0, (
        f"Expected no list items for {text!r}, got {_cues(document)}"
    )


@pytest.mark.parametrize(
    ("text", "expected_item"),
    (
        # "at weak pelvic floors" must remain a single cue (<= 45 chars)
        (
            "Women point the finger at age, at childbirth, at weak pelvic floors",
            "at weak pelvic floors",
        ),
        # "at grief" must stay intact in a 1-comma+and list
        (
            "She pointed at anger, at grief and at fear",
            "at grief",
        ),
    ),
)
def test_list_items_remain_intact(
    alignment_factory,
    text: str,
    expected_item: str,
) -> None:
    """Every individual list item occupies exactly one cue with no internal split."""
    document = _chunk(alignment_factory, text)
    cues = _cues(document)
    assert expected_item in cues, (
        f"Expected item {expected_item!r} as a single cue in {text!r}, got {cues}"
    )


@pytest.mark.parametrize(
    "text",
    (
        "Full or not I make it",
        "Here's what keeps me in business",
        "Pills can hush my alarms for a while",
        "Ready or not we have to begin",
    ),
)
def test_normal_short_phrases_remain_whole_stage15(
    alignment_factory,
    text: str,
) -> None:
    """Natural phrases that fit within 45 characters are never split."""
    assert len(text) <= 45
    document = _chunk(alignment_factory, text)
    cues = _cues(document)
    assert cues == (text,), (
        f"Expected single cue for {text!r}, got {cues}"
    )
