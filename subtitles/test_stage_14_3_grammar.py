from __future__ import annotations

import hashlib
import json
from typing import Callable

import pytest

from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, ScriptTokenKind
from larp_audio_mvp.core.errors import SubtitleValidationError
from larp_audio_mvp.subtitles import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.policy import SEMANTIC_SUBTITLE_POLICY_VERSION


def _document(
    alignment_factory: Callable[..., AlignmentResult], text: str
):
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
        source_alignment_sha256=hashlib.sha256(b"stage-14.3").hexdigest(),
    )


def _texts(document) -> tuple[str, ...]:
    return tuple(block.display_text for block in document.blocks)


def _assert_chain_is_whole(document, chain: str) -> None:
    assert any(chain in block.display_text for block in document.blocks), _texts(document)


def _assert_zero_grammar_violations(document) -> None:
    diagnostics = document.diagnostics
    assert diagnostics.list_item_merge_violation_count == 0
    assert diagnostics.protected_unit_violation_count == 0
    assert diagnostics.adjective_noun_split_count == 0
    assert diagnostics.verb_object_split_count == 0
    assert diagnostics.phrasal_verb_split_count == 0
    assert diagnostics.preposition_object_split_count == 0
    assert diagnostics.number_unit_split_count == 0
    assert diagnostics.product_name_split_count == 0
    assert diagnostics.maximum_display_characters <= 45


def test_reported_wrapped_around_me_regression(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(
        alignment_factory,
        "The muscle wrapped around me stayed loose and patient",
    )
    _assert_chain_is_whole(document, "wrapped around me")
    assert _texts(document) not in {
        ("The muscle wrapped around", "me stayed loose and patient"),
        ("The muscle wrapped", "around me stayed loose and patient"),
    }
    _assert_zero_grammar_violations(document)


def test_reported_parallel_list_is_exactly_isolated(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(
        alignment_factory,
        "at childbirth, at weak pelvic floors, at that second cup of coffee",
    )
    assert _texts(document) == (
        "at childbirth",
        "at weak pelvic floors",
        "at that second cup of coffee",
    )
    assert document.diagnostics.list_item_count == 3
    _assert_chain_is_whole(document, "weak pelvic floors")
    _assert_chain_is_whole(document, "that second cup")
    _assert_zero_grammar_violations(document)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from meat, fish, dairy products",
            ("from meat", "fish", "dairy products"),
        ),
        (
            "redness, discomfort, pressure, and pain",
            ("redness", "discomfort", "pressure", "and pain"),
        ),
        (
            "after childbirth, during exercise, and after coffee",
            ("after childbirth", "during exercise", "and after coffee"),
        ),
        (
            "thinning, receding temples, weak patches, and shedding that won't stop",
            ("thinning", "receding temples", "weak patches", "and shedding that won't stop"),
        ),
    ],
)
def test_genuine_list_items_are_separate_and_keep_final_conjunction(
    alignment_factory: Callable[..., AlignmentResult],
    source: str,
    expected: tuple[str, ...],
) -> None:
    document = _document(alignment_factory, source)
    assert _texts(document) == expected
    assert document.diagnostics.list_item_count == len(expected)
    _assert_zero_grammar_violations(document)


def test_single_non_list_comma_is_not_classified_as_enumeration(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    document = _document(
        alignment_factory, "Now don't get me wrong, these methods can help"
    )
    assert document.diagnostics.list_item_count == 0
    assert _texts(document) == ("Now don't get me wrong", "these methods can help")
    _assert_zero_grammar_violations(document)


@pytest.mark.parametrize(
    "chain",
    [
        "don't know",
        "wouldn't start",
        "get rid of it",
        "wrapped around me",
        "responsible for 95%",
        "95% of male pattern baldness",
        "weak pelvic floors",
        "that second cup",
        "new baby hairs",
        "Spartan Root Activator Shampoo",
        "in just 90 days",
    ],
)
def test_protected_chain_is_not_split(
    alignment_factory: Callable[..., AlignmentResult], chain: str
) -> None:
    source = f"We clearly explain {chain} for everyone today"
    document = _document(alignment_factory, source)
    _assert_chain_is_whole(document, chain)
    assert all(1 <= len(block.display_text) <= 45 for block in document.blocks)
    _assert_zero_grammar_violations(document)


def test_grammar_priority_moves_words_instead_of_breaking_modifier_noun(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    source = "This deliberately longer setup protects the weak pelvic floors during exercise"
    document = _document(alignment_factory, source)
    _assert_chain_is_whole(document, "weak pelvic floors")
    assert "pelvic" not in {block.display_text.split()[-1] for block in document.blocks}
    _assert_zero_grammar_violations(document)


def test_v5_policy_and_metrics_survive_serialization(
    alignment_factory: Callable[..., AlignmentResult], tmp_path
) -> None:
    from larp_audio_mvp.subtitles.serialization import (
        read_subtitle_document,
        write_subtitle_document,
    )

    document = _document(
        alignment_factory,
        "at childbirth, at weak pelvic floors, at that second cup of coffee",
    )
    assert dict(document.configuration_snapshot)["policy_version"] == (
        SEMANTIC_SUBTITLE_POLICY_VERSION
    )
    path = tmp_path / "subtitle_blocks.json"
    write_subtitle_document(document, path)
    loaded = read_subtitle_document(path)
    assert loaded == document
    assert loaded.diagnostics.list_item_count == 3
    assert loaded.diagnostics.protected_unit_count > 0


def test_v5_reader_rejects_forged_grammar_diagnostics(
    alignment_factory: Callable[..., AlignmentResult], tmp_path
) -> None:
    from larp_audio_mvp.subtitles.serialization import (
        read_subtitle_document,
        write_subtitle_document,
    )

    document = _document(
        alignment_factory,
        "at childbirth, at weak pelvic floors, at that second cup of coffee",
    )
    path = tmp_path / "subtitle_blocks.json"
    write_subtitle_document(document, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["diagnostics"]["protected_unit_violation_count"] = 99
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SubtitleValidationError, match="diagnostics"):
        read_subtitle_document(path)
