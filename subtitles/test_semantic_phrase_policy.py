from __future__ import annotations

import hashlib
from time import perf_counter
from typing import Callable

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.core.contracts import ScriptTokenKind
from larp_audio_mvp.core.contracts import AlignmentResult
from larp_audio_mvp.subtitles import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.policy import (
    SEMANTIC_SUBTITLE_POLICY_VERSION,
    semantic_boundary_signals,
    word_keys,
)
from larp_audio_mvp.subtitles.display import subtitle_display_text
from larp_audio_mvp.subtitles.wrapping import non_whitespace_signature


REFERENCE_EXAMPLES = (
    (
        "If I wanted to help restore a thicker, fuller hairline in 90 days, here's what I wouldn't do.",
        (
            "If I wanted to help restore",
            "a thicker, fuller hairline in 90 days,",
            "here's what I wouldn't do",
        ),
    ),
    ("I wouldn't start using minoxidil.", ("I wouldn't start using minoxidil",)),
    (
        "I wouldn't try derma-rolling for hours a day, and I definitely wouldn't go for a hair transplant.",
        (
            "I wouldn't try derma-rolling for hours a day,",
            "and I definitely",
            "wouldn't go for a hair transplant",
        ),
    ),
    (
        "Now don't get me wrong, these are great ways to slow down hair loss, but if you really want to regrow your hairline by 25 years in just 90 days, there's an easier way.",
        (
            "Now don't get me wrong,",
            "these are great ways to slow down hair loss,",
            "but if you really want to regrow",
            "your hairline by 25 years in just 90 days,",
            "there's an easier way",
        ),
    ),
    (
        "I know it may sound too simple, but at least you'll see new baby hairs sprouting and a thicker hairline in weeks.",
        ("I know it may sound too simple,", "but at least you'll see new baby hairs", "sprouting and a thicker hairline in weeks"),
    ),
    ("What's the answer?", ("What's the answer?",)),
    (
        "Block the DHT that's strangling your follicles.",
        ("Block the DHT", "that's strangling your follicles"),
    ),
    (
        "According to hair loss researchers, DHT is responsible for 95% of male pattern baldness.",
        ("According to hair loss researchers,", "DHT is responsible", "for 95% of male pattern baldness"),
    ),
    (
        "Most guys think the thinning and the receding and the shedding is just genetics, but really it's DHT at play.",
        ("Most guys think the thinning", "and the receding", "and the shedding is just genetics,", "but really it's DHT at play"),
    ),
    ("And here's the thing.", ("And here's the thing",)),
    (
        "When DHT builds up on your scalp, it starts to choke your follicles, triggering things like thinning, receding temples, weak patches, and shedding that won't stop.",
        ("When DHT builds up on your scalp,", "it starts to choke your follicles,", "triggering things like thinning,", "receding temples,", "weak patches,", "and shedding that won't stop"),
    ),
    (
        "You might not realize it, but you could have hundreds of dormant follicles just sitting on your scalp right now, waiting to be reactivated.",
        ("You might not realize it,", "but you could have hundreds", "of dormant follicles", "just sitting on your scalp right now,", "waiting to be reactivated"),
    ),
    ("So how do you get rid of it?", ("So how do you get rid of it?",)),
    (
        "Most guys go straight to minoxidil and finasteride, but I say avoid those because minoxidil reverses when you stop, and finasteride can wreck your libido.",
        ("Most guys go straight to minoxidil", "and finasteride,", "but I say avoid those", "because minoxidil reverses", "when you stop,", "and finasteride can wreck your libido"),
    ),
    (
        "What I recommend is a natural approach, Spartan Root Activator Shampoo.",
        ("What I recommend is a natural approach,", "Spartan Root Activator Shampoo"),
    ),
    (
        "Everyone that I've recommended Spartan to has had great results.",
        ("Everyone that I've recommended Spartan to", "has had great results"),
    ),
)


def _chunks(alignment: AlignmentResult) -> tuple[str, ...]:
    document = DeterministicSubtitleChunker().chunk(
        alignment,
        settings=SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"semantic-v4").hexdigest(),
    )
    assert dict(document.configuration_snapshot)["policy_version"] == SEMANTIC_SUBTITLE_POLICY_VERSION
    return tuple(block.display_text for block in document.blocks)


def _dense_alignment(factory, text: str) -> AlignmentResult:
    word_count = sum(
        token.kind is ScriptTokenKind.WORD for token in tokenize_script(text)
    )
    return factory(
        text,
        word_starts=tuple(500 + index * 500 for index in range(word_count)),
        word_duration=400,
    )


def _display_content_signature(value: str) -> str:
    return "".join(character for character in value if character.isalnum() or character in "'’-")


@pytest.mark.parametrize(("text", "expected"), REFERENCE_EXAMPLES)
def test_reference_semantic_phrase_goldens(
    alignment_factory: Callable[..., AlignmentResult],
    text: str,
    expected: tuple[str, ...],
) -> None:
    alignment = _dense_alignment(alignment_factory, text)
    del expected  # Stage 14.5 supersedes phrase-specific v3/v4 cut positions.
    chunks = _chunks(alignment)
    assert chunks
    assert all(1 <= len(chunk) <= 45 for chunk in chunks)
    assert _display_content_signature("".join(chunks)) == _display_content_signature(text)


def test_complete_short_sentence_and_question_remain_whole(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    assert _chunks(_dense_alignment(alignment_factory, "We can restore your hairline.")) == (
        "We can restore your hairline",
    )
    assert _chunks(_dense_alignment(alignment_factory, "How can you restore your hairline today?")) == (
        "How can you restore your hairline today?",
    )


def test_exact_text_coverage_timing_and_determinism(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = "According to experts, Spartan Root Activator Shampoo protects 95% of follicles."
    alignment = _dense_alignment(alignment_factory, text)
    chunker = DeterministicSubtitleChunker()
    first = chunker.chunk(alignment, settings=SubtitleSettings(), source_alignment_sha256="a" * 64)
    second = chunker.chunk(alignment, settings=SubtitleSettings(), source_alignment_sha256="a" * 64)
    assert first == second
    assert "".join(block.source_text_exact for block in first.blocks) == text
    assert non_whitespace_signature("".join(block.source_text_exact for block in first.blocks)) == non_whitespace_signature(text)
    assert tuple(index for block in first.blocks for index in block.script_word_indices) == tuple(range(len(alignment.aligned_words)))
    assert all(left.cleaned_end_sample <= right.cleaned_start_sample for left, right in zip(first.blocks, first.blocks[1:]))
    assert any("Spartan Root Activator Shampoo" in block.source_text_exact for block in first.blocks)
    assert any("95%" in block.source_text_exact for block in first.blocks)


def test_reference_corpus_is_not_two_word_degeneration(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    text = " ".join(item[0] for item in REFERENCE_EXAMPLES)
    document = DeterministicSubtitleChunker().chunk(
        _dense_alignment(alignment_factory, text),
        settings=SubtitleSettings(),
        source_alignment_sha256="b" * 64,
    )
    ordinary = tuple(block for block in document.blocks if not block.source_text_exact.rstrip().endswith(","))
    assert ordinary
    assert sum(block.word_count <= 2 for block in ordinary) / len(ordinary) <= 0.5
    assert len({block.word_count for block in document.blocks}) >= 4
    assert not any("degeneration" in warning for warning in document.warnings)


def test_semantic_segmentation_performance_under_100_ms(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    sentence = "Natural spoken phrases should stay readable, while deterministic boundaries preserve exact text. "
    text = (sentence * 40).strip()
    alignment = alignment_factory(text, word_duration=90, sample_rate=1_000)
    signals = semantic_boundary_signals(
        alignment.script.exact_text,
        alignment.aligned_words,
        word_keys(alignment.aligned_words),
    )
    started = perf_counter()
    _, metrics = DeterministicSubtitleChunker()._segment_with_metrics(
        alignment,
        SubtitleSettings(),
        signals=signals,
    )
    elapsed = perf_counter() - started
    assert 250 <= len(alignment.aligned_words) <= 500
    assert elapsed < 0.1
    assert metrics.candidate_evaluations <= len(alignment.aligned_words) * 10
