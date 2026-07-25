from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

import pytest

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, SubtitleDocument
from larp_audio_mvp.subtitles.chunker import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.policy import semantic_boundary_signals, word_keys
from larp_audio_mvp.subtitles.syntax import (
    BoundaryLegality,
    LocalEnglishSyntaxAnalyzer,
    SyntaxAnalyzerMode,
)


def _chunk(
    alignment_factory: Callable[..., AlignmentResult], text: str
) -> SubtitleDocument:
    return DeterministicSubtitleChunker().chunk(
        alignment_factory(text),
        settings=SubtitleSettings(),
        source_alignment_sha256="5" * 64,
    )


def _assert_phrase_intact(document: SubtitleDocument, phrase: str) -> None:
    assert any(
        phrase.casefold() in line.casefold()
        for block in document.blocks
        for line in block.display_lines
    ), tuple(block.display_lines for block in document.blocks)


def _assert_zero_syntax_violations(document: SubtitleDocument) -> None:
    diagnostics = document.diagnostics
    for name in (
        "forced_syntax_split_count",
        "auxiliary_verb_split_count",
        "verb_particle_split_count",
        "verb_object_split_count",
        "preposition_object_split_count",
        "adjective_noun_split_count",
        "compound_noun_split_count",
        "degree_modifier_split_count",
        "temporal_connector_split_count",
        "number_unit_split_count",
        "proper_name_split_count",
        "orphan_fragment_count",
        "incomplete_ending_count",
        "list_item_merge_violation_count",
    ):
        assert getattr(diagnostics, name) == 0, name
    assert diagnostics.maximum_display_characters <= 45


def test_primary_analyzer_has_real_pos_dependency_and_exact_offsets(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory(
        "The procedure was carried out by trained nurses."
    )
    analysis = LocalEnglishSyntaxAnalyzer(allow_fallback=False).analyze(
        alignment.script.exact_text, alignment.aligned_words
    )
    assert analysis.mode is SyntaxAnalyzerMode.SPACY_EN_CORE_WEB_SM
    assert analysis.model_name == "en_core_web_sm"
    assert len(analysis.features) == len(alignment.aligned_words)
    assert any(feature.dependency_relation != "dep" for feature in analysis.features)
    for word, feature in zip(alignment.aligned_words, analysis.features):
        assert alignment.script.exact_text[feature.char_start : feature.char_end] == word.exact_text
        assert feature.original_text == word.exact_text == feature.display_text


def test_controlled_fallback_is_explicit(
    alignment_factory: Callable[..., AlignmentResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    alignment = alignment_factory("The local parser remains private and deterministic.")
    analyzer = LocalEnglishSyntaxAnalyzer()

    def fail_load() -> tuple[object, int, str | None]:
        raise RuntimeError("synthetic model load failure")

    monkeypatch.setattr(analyzer, "_load_pipeline", fail_load)
    analysis = analyzer.analyze(alignment.script.exact_text, alignment.aligned_words)
    assert analysis.mode is SyntaxAnalyzerMode.DETERMINISTIC_FALLBACK
    assert analysis.warnings
    assert "fallback" in analysis.warnings[0]


def test_warm_parser_budget_for_normal_script(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    sentence = "Clear spoken phrases preserve exact words while local syntax guides readable timing. "
    alignment = alignment_factory((sentence * 35).strip(), word_duration=90)
    second = alignment_factory(
        ((sentence.replace("Clear", "Natural")) * 35).strip(),
        word_duration=90,
    )
    analyzer = LocalEnglishSyntaxAnalyzer(allow_fallback=False)
    analyzer.analyze(alignment.script.exact_text, alignment.aligned_words)
    started = perf_counter()
    analysis = analyzer.analyze(second.script.exact_text, second.aligned_words)
    elapsed = perf_counter() - started
    assert 250 <= len(second.aligned_words) <= 500
    assert analysis.mode is SyntaxAnalyzerMode.SPACY_EN_CORE_WEB_SM
    assert elapsed < 0.15


@pytest.mark.parametrize(
    ("text", "phrases"),
    [
        (
            "Swallowed supplements get broken down by digestion long before much of anything reaches the bloodstream.",
            ("broken down", "long before"),
        ),
        (
            "That soothing feeling moved even deeper into the pelvic floor around me.",
            ("even deeper", "pelvic floor", "around me"),
        ),
    ],
)
def test_reported_regressions_are_fixed_by_general_syntax(
    alignment_factory: Callable[..., AlignmentResult],
    text: str,
    phrases: tuple[str, ...],
) -> None:
    document = _chunk(alignment_factory, text)
    for phrase in phrases:
        _assert_phrase_intact(document, phrase)
    _assert_zero_syntax_violations(document)


@pytest.mark.parametrize(
    ("text", "phrases"),
    [
        ("The capsules break down in the stomach before anything reaches the bloodstream.", ("break down", "in the stomach", "before anything")),
        ("She felt even stronger after the treatment.", ("even stronger", "after the treatment")),
        ("The procedure was carried out by trained nurses.", ("carried out", "by trained nurses")),
        ("It stayed wrapped around her during the night.", ("wrapped around her", "during the night")),
        ("The signal travels through the nervous system into the brain.", ("nervous system", "into the brain")),
        ("The relief appeared shortly after the second treatment.", ("shortly after", "the second treatment")),
    ],
)
def test_unseen_holdouts_preserve_constituents(
    alignment_factory: Callable[..., AlignmentResult],
    text: str,
    phrases: tuple[str, ...],
) -> None:
    document = _chunk(alignment_factory, text)
    for phrase in phrases:
        _assert_phrase_intact(document, phrase)
    _assert_zero_syntax_violations(document)


@pytest.mark.parametrize(
    "phrase",
    ("break down", "breaks down", "broke down", "broken down", "breaking down"),
)
def test_verb_particle_inflection_mutations(
    alignment_factory: Callable[..., AlignmentResult], phrase: str
) -> None:
    document = _chunk(alignment_factory, f"These capsules can {phrase} in the stomach during digestion.")
    _assert_phrase_intact(document, phrase)
    assert document.diagnostics.verb_particle_split_count == 0


@pytest.mark.parametrize(
    "phrase",
    ("wrap around me", "wrapped around her", "wrapping around them"),
)
def test_verb_preposition_pronoun_mutations(
    alignment_factory: Callable[..., AlignmentResult], phrase: str
) -> None:
    document = _chunk(alignment_factory, f"The soft material kept {phrase} during the procedure.")
    _assert_phrase_intact(document, phrase)
    assert document.diagnostics.preposition_object_split_count == 0


@pytest.mark.parametrize(
    "phrase",
    ("even deeper", "much deeper", "slightly deeper", "far deeper"),
)
def test_degree_modifier_mutations(
    alignment_factory: Callable[..., AlignmentResult], phrase: str
) -> None:
    document = _chunk(alignment_factory, f"The sensation moved {phrase} into the tissue after treatment.")
    _assert_phrase_intact(document, phrase)
    assert document.diagnostics.degree_modifier_split_count == 0


@pytest.mark.parametrize(
    "phrase",
    ("long before", "shortly before", "right before", "just before"),
)
def test_temporal_connector_mutations(
    alignment_factory: Callable[..., AlignmentResult], phrase: str
) -> None:
    document = _chunk(alignment_factory, f"The effect appeared {phrase} the scheduled procedure started.")
    _assert_phrase_intact(document, phrase)
    assert document.diagnostics.temporal_connector_split_count == 0


def test_forbidden_boundary_model_is_explicit(
    alignment_factory: Callable[..., AlignmentResult],
) -> None:
    alignment = alignment_factory("The procedure was carried out by trained nurses.")
    signals = semantic_boundary_signals(
        alignment.script.exact_text,
        alignment.aligned_words,
        word_keys(alignment.aligned_words),
    )
    words = [word.exact_text for word in alignment.aligned_words]
    boundary = words.index("out")
    assert boundary in signals.grammar.syntax.forbidden_boundaries
    assert BoundaryLegality.FORBIDDEN.value == "forbidden"


def test_production_source_has_no_reported_phrase_exception_tables() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "larp_audio_mvp" / "subtitles"
    forbidden = (
        "broken down by digestion",
        "pelvic floors",
        "wrapped around me",
        "for a while",
        "pills can hush my alarms",
    )
    payload = "\n".join(
        path.read_text(encoding="utf-8").casefold()
        for path in sorted(root.glob("*.py"))
    )
    for phrase in forbidden:
        assert phrase not in payload
