from __future__ import annotations

from fractions import Fraction

import pytest

from larp_audio_mvp.alignment import ScriptAsrAlignmentEngine, tokenize_script
from larp_audio_mvp.alignment.engine import string_similarity
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import AlignmentMatchType, RecognizedWord, ScriptTokenKind
from larp_audio_mvp.core.errors import AlignmentLimitExceededError


def _words(text: str):
    return tuple(token for token in tokenize_script(text) if token.kind is ScriptTokenKind.WORD)


def _asr(*values: str) -> tuple[RecognizedWord, ...]:
    return tuple(
        RecognizedWord(
            text=value,
            sample_rate=1_000,
            start_sample_cleaned=index * 100 + 10,
            end_sample_cleaned=index * 100 + 90,
            start_sample_original=index * 100 + 10,
            end_sample_original=index * 100 + 90,
        )
        for index, value in enumerate(values)
    )


def _types(script: str, *asr: str, settings: AlignmentSettings | None = None):
    engine = ScriptAsrAlignmentEngine(settings or AlignmentSettings())
    return tuple(op.match_type for op in engine.align(_words(script), _asr(*asr)))


def test_exact_normalized_and_fuzzy_matching() -> None:
    assert _types("Hello", "Hello") == (AlignmentMatchType.EXACT,)
    assert _types("Don’t", "don't") == (AlignmentMatchType.NORMALIZED,)
    assert _types("testing", "testin") == (AlignmentMatchType.FUZZY,)
    assert string_similarity("testing", "testin") == Fraction(6, 7)


def test_fuzzy_is_forbidden_for_short_words() -> None:
    assert _types("to", "ta") == (AlignmentMatchType.SUBSTITUTION,)
    assert _types("я", "а") == (AlignmentMatchType.SUBSTITUTION,)


def test_insertions_deletions_and_substitutions_are_explicit() -> None:
    assert _types("hello world", "hello", "um", "world") == (
        AlignmentMatchType.EXACT,
        AlignmentMatchType.UNRESOLVED,
        AlignmentMatchType.EXACT,
    )
    assert _types("hello brave world", "hello", "world") == (
        AlignmentMatchType.EXACT,
        AlignmentMatchType.UNRESOLVED,
        AlignmentMatchType.EXACT,
    )
    assert _types("hello earth", "hello", "planet")[-1] is AlignmentMatchType.SUBSTITUTION


def test_one_to_many_and_many_to_one_are_bounded_and_deterministic() -> None:
    assert _types("cannot", "can", "not") == (
        AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR,
    )
    assert _types("new york", "newyork") == (
        AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR,
    )
    first = _types("a b", "a", "x", "b")
    assert first == _types("a b", "a", "x", "b")


def test_split_merge_can_be_disabled() -> None:
    settings = AlignmentSettings(enable_split_merge=False)
    assert AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR not in _types(
        "cannot", "can", "not", settings=settings
    )


def test_dp_cell_limit_fails_before_allocation() -> None:
    engine = ScriptAsrAlignmentEngine(AlignmentSettings(max_dp_cells=4))
    with pytest.raises(AlignmentLimitExceededError) as captured:
        engine.align(_words("one two"), _asr("one", "two"))
    assert captured.value.code == "ALIGNMENT_DP_LIMIT_EXCEEDED"
