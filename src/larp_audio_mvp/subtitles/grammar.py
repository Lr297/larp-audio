"""Compatibility facade over the general local syntax analyzer.

Stage 14.5 deliberately contains no reported-phrase tables.  The public
``GrammarSignals`` names are retained for already-tested callers while their
content now comes from POS/dependency/NER analysis.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from larp_audio_mvp.subtitles.syntax import LocalEnglishSyntaxAnalyzer, SyntaxAnalysis


@dataclass(frozen=True, slots=True)
class GrammarSignals:
    syntax: SyntaxAnalysis
    list_item: frozenset[int]
    list_item_count: int
    adjective_noun: frozenset[int]
    verb_object: frozenset[int]
    phrasal_verb: frozenset[int]
    preposition_object: frozenset[int]
    number_unit: frozenset[int]
    product_name: frozenset[int]
    determiner_noun: frozenset[int]
    auxiliary_verb: frozenset[int]
    compound_noun: frozenset[int]
    degree_modifier: frozenset[int]
    temporal_connector: frozenset[int]
    subordinator_clause: frozenset[int]
    proper_name: frozenset[int]
    or_not: frozenset[int]
    wh_clause: frozenset[int]
    protected: frozenset[int]


@dataclass(frozen=True, slots=True)
class GrammarQualityMetrics:
    list_item_count: int = 0
    list_item_merge_violation_count: int = 0
    protected_unit_count: int = 0
    protected_unit_violation_count: int = 0
    adjective_noun_split_count: int = 0
    verb_object_split_count: int = 0
    phrasal_verb_split_count: int = 0
    preposition_object_split_count: int = 0
    number_unit_split_count: int = 0
    product_name_split_count: int = 0
    auxiliary_verb_split_count: int = 0
    verb_particle_split_count: int = 0
    compound_noun_split_count: int = 0
    degree_modifier_split_count: int = 0
    temporal_connector_split_count: int = 0
    proper_name_split_count: int = 0
    forced_syntax_split_count: int = 0
    list_item_internal_split_count: int = 0
    wh_clause_split_count: int = 0
    or_not_split_count: int = 0


def analyze_grammar(
    exact_text: str,
    words: Sequence[object],
    keys: Sequence[str],
    *,
    sentence_boundaries: frozenset[int] = frozenset(),
    comma_boundaries: frozenset[int] = frozenset(),
    syntax_analysis: SyntaxAnalysis | None = None,
) -> GrammarSignals:
    del keys, sentence_boundaries, comma_boundaries
    syntax = syntax_analysis or LocalEnglishSyntaxAnalyzer().analyze(exact_text, words)
    category = {
        name: frozenset(values & syntax.forbidden_boundaries)
        for name, values in syntax.protected_by_category
    }
    adjective = category.get("adjective_noun", frozenset())
    compound = category.get("compound_noun", frozenset())
    proper = category.get("proper_name", frozenset())
    verb_particle = category.get("verb_particle", frozenset())
    protected = syntax.forbidden_boundaries
    comma_boundaries = {
        position
        for position in range(1, len(words))
        if "," in exact_text[
            int(getattr(words[position - 1], "char_end")):
            int(getattr(words[position], "char_start"))
        ]
    }
    has_intro_boundary = bool(
        syntax.list_item_boundaries - comma_boundaries
    )
    list_count = (
        len(syntax.list_item_boundaries)
        + (0 if has_intro_boundary else 1)
        if syntax.list_item_boundaries
        else 0
    )
    return GrammarSignals(
        syntax=syntax,
        list_item=syntax.list_item_boundaries,
        list_item_count=list_count,
        adjective_noun=frozenset(adjective),
        verb_object=category.get("verb_object", frozenset()),
        phrasal_verb=verb_particle,
        preposition_object=category.get("preposition_object", frozenset()),
        number_unit=category.get("number_unit", frozenset()),
        product_name=proper,
        determiner_noun=category.get("determiner_noun", frozenset()),
        auxiliary_verb=category.get("auxiliary_verb", frozenset()),
        compound_noun=frozenset(compound),
        degree_modifier=category.get("degree_modifier", frozenset()),
        temporal_connector=category.get("temporal_connector", frozenset()),
        subordinator_clause=category.get("subordinator_clause", frozenset()),
        proper_name=frozenset(proper),
        or_not=category.get("or_not", frozenset()),
        wh_clause=category.get("wh_clause", frozenset()),
        protected=protected,
    )


def grammar_quality_metrics(
    signals: GrammarSignals, block_boundaries: frozenset[int]
) -> GrammarQualityMetrics:
    def count(values: frozenset[int]) -> int:
        return len(values & block_boundaries)

    verb_particle = count(signals.phrasal_verb)
    proper_name = count(signals.proper_name)
    violations = count(signals.protected)
    return GrammarQualityMetrics(
        list_item_count=signals.list_item_count,
        list_item_merge_violation_count=len(signals.list_item - block_boundaries),
        protected_unit_count=len(signals.protected),
        protected_unit_violation_count=violations,
        adjective_noun_split_count=count(signals.adjective_noun),
        verb_object_split_count=count(signals.verb_object),
        phrasal_verb_split_count=verb_particle,
        preposition_object_split_count=count(signals.preposition_object),
        number_unit_split_count=count(signals.number_unit),
        product_name_split_count=proper_name,
        auxiliary_verb_split_count=count(signals.auxiliary_verb),
        verb_particle_split_count=verb_particle,
        compound_noun_split_count=count(signals.compound_noun),
        degree_modifier_split_count=count(signals.degree_modifier),
        temporal_connector_split_count=count(signals.temporal_connector),
        proper_name_split_count=proper_name,
        forced_syntax_split_count=violations,
        wh_clause_split_count=count(signals.wh_clause),
        or_not_split_count=count(signals.or_not),
    )
