from __future__ import annotations

import hashlib
from typing import Callable

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult
from larp_audio_mvp.core.errors import SubtitleValidationError
from larp_audio_mvp.subtitles import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.serialization import (
    subtitle_document_from_dict,
    subtitle_document_to_dict,
)


def _chunk(alignment: AlignmentResult, settings: SubtitleSettings | None = None):
    return DeterministicSubtitleChunker().chunk(
        alignment,
        settings=settings or SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"corpus").hexdigest(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "One, two, three, four, five.",
        "This is simple, fast, and easy to use.",
        "One word after another with small pauses",
        "Просто, швидко, надійно й красиво.",
        "Rýchle, ľahké a presné riešenie.",
    ],
)
def test_semantic_corpus_is_deterministic_and_bounded(
    alignment_factory: Callable[..., AlignmentResult], text: str
) -> None:
    alignment = alignment_factory(text)
    first = _chunk(alignment)
    second = _chunk(alignment)
    assert first == second
    assert all(1 <= block.word_count <= 10 for block in first.blocks)
    assert "".join(block.source_text_exact for block in first.blocks) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Stop!\nDo not touch it.", 2),
        ("Wait.\nListen carefully.\nThis changes everything.", 3),
        ("Limited time only.\nGet yours today!", 2),
    ],
)
def test_strong_sentence_boundaries_remain_logical(
    alignment_factory: Callable[..., AlignmentResult], text: str, expected: int
) -> None:
    document = _chunk(alignment_factory(text))
    assert len(document.blocks) >= expected
    assert document.diagnostics.blocks_created_at_sentence_boundary >= 1
    assert all(block.word_count <= 10 for block in document.blocks)


def test_soft_gaps_do_not_over_fragment_phrases(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = "One word after another with small pauses"
    starts = tuple(500 + index * 950 for index in range(7))  # 450 ms gaps
    document = _chunk(alignment_factory(text, word_starts=starts))
    assert all(block.word_count <= 10 for block in document.blocks)
    assert len(document.blocks) <= 2
    assert all(block.word_count > 1 for block in document.blocks)


def test_strong_gap_does_not_split_a_compact_complete_phrase(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    starts = (500, 1_500, 2_500, 5_000, 6_000, 7_000)
    document = _chunk(
        alignment_factory("First phrase here second phrase now", word_starts=starts)
    )
    assert len(document.blocks) == 1
    assert document.diagnostics.blocks_created_at_gap_boundary == 0


def test_semantic_ceiling_and_duration_limits_force_segmentation(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    by_words = _chunk(
        alignment_factory("one two three four five six seven eight nine ten eleven twelve")
    )
    assert len(by_words.blocks) >= 2
    assert all(block.word_count <= 10 for block in by_words.blocks)
    by_duration = _chunk(
        alignment_factory("one two three four five", word_duration=400),
        SubtitleSettings(max_duration_ms=1_900),
    )
    assert len(by_duration.blocks) >= 3
    assert all(block.duration_samples <= 1_900 for block in by_duration.blocks)


def test_long_word_remains_whole_as_acceptable_single_block(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _chunk(
        alignment_factory("supercalifragilisticexpialidocious"),
        SubtitleSettings(max_characters_per_line=8),
    )
    assert document.diagnostics.single_word_blocks == 1
    assert "supercalifragilisticexpialidocious" in document.blocks[0].display_lines


def test_strict_reader_recalculates_fragmentation_diagnostics(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _chunk(alignment_factory("one two three four"))
    payload = subtitle_document_to_dict(document)
    payload["diagnostics"]["single_word_blocks"] = 999
    with pytest.raises(SubtitleValidationError):
        subtitle_document_from_dict(payload)
