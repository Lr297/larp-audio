from __future__ import annotations

import hashlib
from time import perf_counter_ns
from typing import Callable

import pytest

from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, ScriptTokenKind
from larp_audio_mvp.exports import render_srt, subtitle_cues, validate_srt
from larp_audio_mvp.subtitles import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.display import subtitle_display_text
from larp_audio_mvp.subtitles.repair import repair_orphan_ranges
from larp_audio_mvp.subtitles.wrapping import layout_semantic_cue


def _document(alignment_factory: Callable[..., AlignmentResult], text: str):
    word_count = sum(
        token.kind is ScriptTokenKind.WORD for token in tokenize_script(text)
    )
    alignment = alignment_factory(
        text,
        word_starts=tuple(500 + index * 500 for index in range(word_count)),
        word_duration=400,
    )
    return DeterministicSubtitleChunker().chunk(
        alignment,
        settings=SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"stage-14.4").hexdigest(),
    )


def test_golden_for_a_while_is_one_two_line_cue(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    source = "Pills can hush my alarms for a while,"
    document = _document(alignment_factory, source)
    assert len(document.blocks) == 1
    block = document.blocks[0]
    assert block.source_text_exact == source
    assert block.display_text_plain == "Pills can hush my alarms for a while"
    assert len(block.display_text_plain) == 36
    assert block.display_lines == ("Pills can hush my alarms", "for a while")
    assert block.render_text == "Pills can hush my alarms\nfor a while"
    diagnostics = document.diagnostics
    assert diagnostics.cue_count == 1
    assert diagnostics.two_line_cue_count == 1
    assert diagnostics.orphan_fragment_count == 0
    assert diagnostics.incomplete_ending_count == 0
    assert diagnostics.protected_unit_violation_count == 0
    assert diagnostics.trailing_period_violation_count == 0
    assert diagnostics.trailing_comma_violation_count == 0
    assert diagnostics.three_line_cue_count == 0
    assert diagnostics.empty_line_count == 0
    assert diagnostics.maximum_plain_characters == 36
    assert diagnostics.maximum_render_line_characters == 24


@pytest.mark.parametrize(
    ("source", "display"),
    [
        ("It worked for several years,", "It worked for several years"),
        ("I noticed it in the morning,", "I noticed it in the morning"),
        ("The muscle wrapped around me,", "The muscle wrapped around me"),
        ("at weak pelvic floors,", "at weak pelvic floors"),
    ],
)
def test_compact_grammar_tail_stays_whole(
    alignment_factory: Callable[..., AlignmentResult], source: str, display: str
) -> None:
    document = _document(alignment_factory, source)
    assert tuple(block.display_text_plain for block in document.blocks) == (display,)
    assert document.diagnostics.orphan_fragment_count == 0
    assert document.diagnostics.incomplete_ending_count == 0
    assert document.diagnostics.protected_unit_violation_count == 0


@pytest.mark.parametrize(
    ("source", "display"),
    [
        ("Simple comma,", "Simple comma"),
        ('"Try this,"', '"Try this"'),
        ("Try this,)", "Try this)"),
        ("Now listen this is important", "Now listen this is important"),
        ("One two three!", "One two three!"),
        ("Wait...", "Wait..."),
        ("Really?", "Really?"),
        ("Value 3.5.", "Value 3.5"),
    ],
)
def test_terminal_punctuation_display_transform(source: str, display: str) -> None:
    assert subtitle_display_text(source) == display


def test_repair_directly_merges_incomplete_pair() -> None:
    ranges, metrics = repair_orphan_ranges(
        ((0, 7), (7, 8)),
        keys=("pills", "can", "hush", "my", "alarms", "for", "a", "while"),
        protected=frozenset({6, 7}),
        mandatory=frozenset(),
        candidate_is_valid=lambda start, end: end - start <= 8,
    )
    assert ranges == ((0, 8),)
    assert metrics.direct_merges == 1


def test_repair_rebalances_when_direct_merge_does_not_fit() -> None:
    keys = (
        "a", "very", "long", "preceding", "phrase", "ending",
        "for", "a", "while", "the", "next", "clause",
    )
    ranges, metrics = repair_orphan_ranges(
        ((0, 8), (8, 12)),
        keys=keys,
        protected=frozenset({7, 8}),
        mandatory=frozenset(),
        candidate_is_valid=lambda start, end: end - start <= 7,
    )
    assert ranges == ((0, 6), (6, 12))
    assert metrics.rebalanced_boundaries == 1
    assert ranges[0][1] not in {7, 8}


def test_layout_is_one_or_two_lines_and_preserves_protected_units() -> None:
    assert layout_semantic_cue("Short complete cue") == ("Short complete cue",)
    assert layout_semantic_cue(
        "Pills can hush my alarms for a while",
        protected_boundaries=frozenset({6, 7}),
    ) == ("Pills can hush my alarms", "for a while")
    cyrillic = layout_semantic_cue(
        "Это достаточно длинная естественная фраза"
    )
    assert 1 <= len(cyrillic) <= 2
    assert " ".join(cyrillic) == "Это достаточно длинная естественная фраза"
    assert all(line and line == line.strip() for line in cyrillic)


def test_multiline_srt_is_same_single_gapless_cue(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(alignment_factory, "Pills can hush my alarms for a while,")
    payload = render_srt(document)
    text = payload.decode("utf-8")
    assert "Pills can hush my alarms\r\nfor a while" in text
    assert text.count(" --> ") == 1
    assert len(subtitle_cues(document)) == 1
    validate_srt(payload, document)


def test_repair_and_layout_are_bounded_for_normal_script() -> None:
    keys = tuple("normal phrase timing remains deterministic for a while".split())
    started = perf_counter_ns()
    for _ in range(200):
        ranges, _ = repair_orphan_ranges(
            ((0, 7), (7, 8)),
            keys=keys,
            protected=frozenset({6, 7}),
            mandatory=frozenset(),
            candidate_is_valid=lambda start, end: end - start <= 8,
        )
        assert ranges == ((0, 8),)
        layout_semantic_cue("Pills can hush my alarms for a while")
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    assert elapsed_ms < 40
