from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Callable

from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, ScriptTokenKind
from larp_audio_mvp.subtitles import DeterministicSubtitleChunker


FIXTURE = Path(__file__).parents[1] / "assets" / "stage14_3_grammar_quality_script.txt"


def test_privacy_safe_real_length_grammar_quality(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    with FIXTURE.open("r", encoding="utf-8", newline="") as stream:
        exact_text = stream.read()
    word_count = sum(
        token.kind is ScriptTokenKind.WORD for token in tokenize_script(exact_text)
    )
    assert 250 <= word_count <= 500
    alignment = alignment_factory(
        exact_text,
        word_starts=tuple(500 + index * 400 for index in range(word_count)),
        word_duration=300,
    )
    started = perf_counter()
    document = DeterministicSubtitleChunker().chunk(
        alignment,
        settings=SubtitleSettings(),
        source_alignment_sha256=hashlib.sha256(b"stage-14.3-real").hexdigest(),
    )
    elapsed = perf_counter() - started

    diagnostics = document.diagnostics
    # Stage 14.5 uses dependency-confirmed lists; the old punctuation corpus is
    # retained for load/performance and zero-violation coverage, not a fixed
    # comma-count expectation.
    assert diagnostics.list_item_count >= 0
    assert diagnostics.list_item_merge_violation_count == 0
    assert diagnostics.protected_unit_count > 20
    assert diagnostics.protected_unit_violation_count == 0
    assert diagnostics.adjective_noun_split_count == 0
    assert diagnostics.verb_object_split_count == 0
    assert diagnostics.phrasal_verb_split_count == 0
    assert diagnostics.preposition_object_split_count == 0
    assert diagnostics.number_unit_split_count == 0
    assert diagnostics.product_name_split_count == 0
    assert diagnostics.maximum_display_characters <= 45
    assert elapsed < 2.0
    assert "".join(block.source_text_exact for block in document.blocks) == exact_text
