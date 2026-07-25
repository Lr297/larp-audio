"""Versioned syntax-constrained subtitle segmentation policies."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from larp_audio_mvp.core.contracts import AlignedScriptWord
from larp_audio_mvp.subtitles.display import is_sentence_period_at
from larp_audio_mvp.subtitles.grammar import GrammarSignals, analyze_grammar

SEMANTIC_SUBTITLE_POLICY_VERSION = (
    "conservative-subtitles-v8-syntax-guardrails-45chars-gapless"
)
LEGACY_SYNTAX_SUBTITLE_POLICY_VERSION = (
    "syntax-aware-subtitles-v7-spacy-en-45chars-gapless"
)
LEGACY_ORPHAN_REPAIR_POLICY_VERSION = (
    "semantic-phrase-subtitles-v6-orphan-repair-two-line-45chars-gapless"
)
LEGACY_GRAMMAR_SUBTITLE_POLICY_VERSION = (
    "semantic-phrase-subtitles-v5-grammar-lists-45chars-gapless"
)
LEGACY_PERIOD_FREE_SUBTITLE_POLICY_VERSION = (
    "semantic-phrase-subtitles-v4-45chars-no-periods-gapless"
)
LEGACY_SEMANTIC_SUBTITLE_POLICY_VERSION = "semantic-phrase-subtitles-v3"
RAPID_SUBTITLE_POLICY_VERSION = "subtitle-segmentation-v2-rapid-1-to-3"
LEGACY_SUBTITLE_POLICY_VERSION = "subtitle-dp-v2"
# The production policy is character-bound (45 visible characters), not
# word-bound.  Forty-five is therefore only a finite DP look-ahead guard: a
# legal 45-character cue cannot contain more than 45 non-empty word tokens.
# The historical 10-word setting remains serialized for configuration
# compatibility but must not force a split inside a parser-protected unit.
SEMANTIC_MAX_WORDS = 45
SEMANTIC_MAX_VISIBLE_CHARACTERS = 45
LEGACY_SEMANTIC_MAX_VISIBLE_CHARACTERS = 60
RAPID_MAX_WORDS = 3

_ARTICLES = frozenset({"a", "an", "the"})
_DETERMINERS = _ARTICLES | frozenset(
    {"his", "her", "its", "my", "our", "their", "this", "those", "your"}
)
_PREPOSITIONS = frozenset(
    {
        "at", "by", "for", "from", "in", "into", "of", "on", "onto",
        "through", "to", "with", "without",
    }
)
_CONJUNCTIONS = frozenset({"and", "but", "so", "because", "when", "if", "while"})
_AUXILIARIES = frozenset(
    {
        "am", "are", "be", "been", "being", "can", "can't", "could",
        "couldn't", "did", "didn't", "do", "does", "doesn't", "don't",
        "had", "has", "have", "is", "may", "might", "must", "should",
        "shouldn't", "was", "were", "will", "won't", "would", "wouldn't",
    }
)
_BOUND_AUXILIARY_FORMS = frozenset(
    {"that's", "there's", "what's", "who's", "you're", "we're", "they're"}
)
_PRONOUNS = frozenset({"he", "i", "it", "she", "they", "we", "you"})
_WORDISH = re.compile(r"[\w%]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class BoundarySignals:
    """Precomputed local boundary evidence indexed by script-word position."""

    sentence: frozenset[int]
    line: frozenset[int]
    comma: frozenset[int]
    structural_comma: frozenset[int]
    clause: frozenset[int]
    preferred: frozenset[int]
    grammar: GrammarSignals

    @property
    def required(self) -> frozenset[int]:
        """Boundaries that must survive optimization."""

        return frozenset(self.sentence | self.comma)


class BoundaryPriority(StrEnum):
    """Conservative role of a possible semantic-cue boundary."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    NEUTRAL = "neutral"
    FORBIDDEN = "forbidden"


def boundary_priority(position: int, signals: BoundarySignals) -> BoundaryPriority:
    """Classify a boundary without turning parser nodes into required cuts."""

    if position in signals.required:
        return BoundaryPriority.REQUIRED
    if position in signals.grammar.syntax.forbidden_boundaries:
        return BoundaryPriority.FORBIDDEN
    if (
        position in signals.structural_comma
        or position in signals.clause
        or position in signals.preferred
    ):
        return BoundaryPriority.PREFERRED
    return BoundaryPriority.NEUTRAL


def comparison_key(value: str) -> str:
    """Return a deterministic key for decisions, never for display text."""

    return (
        unicodedata.normalize("NFKC", value)
        .casefold()
        .replace("’", "'")
        .replace("‘", "'")
    )


def word_keys(words: Sequence[AlignedScriptWord]) -> tuple[str, ...]:
    return tuple(comparison_key(word.exact_text) for word in words)


def semantic_boundary_signals(
    exact_text: str,
    words: Sequence[AlignedScriptWord],
    keys: Sequence[str],
) -> BoundarySignals:
    grammar = analyze_grammar(exact_text, words, keys)
    sentence: set[int] = set(grammar.syntax.sentence_boundaries)
    lines: set[int] = set()
    commas: set[int] = set()
    clauses: set[int] = set()
    preferred: set[int] = set()
    for position in range(1, len(words)):
        separator = exact_text[words[position - 1].char_end : words[position].char_start]
        if "\n" in separator or "\r" in separator:
            lines.add(position)
            sentence.add(position)
        if _contains_sentence_punctuation(exact_text, words[position - 1].char_end, words[position].char_start):
            sentence.add(position)
        if "," in separator:
            commas.add(position)
    clauses.update(grammar.syntax.clause_boundaries)
    structural_commas = frozenset(
        position
        for position in commas
        if not _is_soft_modifier_comma(keys, position)
    )
    return BoundarySignals(
        sentence=frozenset(sentence),
        line=frozenset(lines),
        comma=frozenset(commas),
        structural_comma=structural_commas,
        clause=frozenset(clauses),
        preferred=frozenset(preferred),
        grammar=grammar,
    )


def _is_soft_modifier_comma(keys: Sequence[str], position: int) -> bool:
    """Treat a comma between two modifier-shaped words as non-structural."""

    return (
        0 < position < len(keys) - 1
        and keys[position - 1].endswith(("al", "ed", "er", "ful", "ic", "ive", "ous"))
        and keys[position].endswith(("al", "ed", "er", "ful", "ic", "ive", "ous"))
    )


def sentence_boundary_positions(
    exact_text: str, words: Sequence[AlignedScriptWord]
) -> frozenset[int]:
    keys = word_keys(words)
    return semantic_boundary_signals(exact_text, words, keys).sentence


def hard_boundary_positions(
    exact_text: str, words: Sequence[AlignedScriptWord]
) -> frozenset[int]:
    """Return historical v2 hard boundaries, including commas."""

    keys = word_keys(words)
    signals = semantic_boundary_signals(exact_text, words, keys)
    return frozenset(signals.sentence | signals.comma)


def _contains_sentence_punctuation(text: str, start: int, end: int) -> bool:
    for offset in range(start, end):
        character = text[offset]
        if character in "?!…":
            return True
        if character == "." and is_sentence_period_at(text, offset):
            return True
    return False


def crosses_boundary(start: int, end: int, boundaries: frozenset[int]) -> bool:
    return any(position in boundaries for position in range(start + 1, end))


def semantic_candidate_cost(
    *,
    keys: Sequence[str],
    exact_words: Sequence[str],
    start: int,
    end: int,
    source_text: str,
    signals: BoundarySignals,
) -> int:
    """Rank equally sparse segmentations; lower values are preferred.

    Cue count is deliberately not encoded here.  The DP compares cue count
    before this placement cost, so parser-derived boundaries cannot create an
    extra cue merely to improve balance.
    """

    group = tuple(keys[start:end])
    length = end - start
    visible = len(source_text.strip())
    cost = 0

    # Among solutions with the same minimum cue count, avoid tiny fragments.
    if visible < 12:
        cost += (12 - visible) * 80
    if length == 1:
        cost += 1_200

    sentence_start = start == 0 or start in signals.sentence
    sentence_end = end == len(keys) or end in signals.sentence
    if sentence_start and sentence_end:
        cost -= 600

    if end in signals.grammar.list_item:
        cost -= 8_000
    if start in signals.grammar.list_item:
        cost -= 800

    if end in signals.comma:
        cost -= 1_200
    if end in signals.clause:
        cost -= 700
    if end in signals.preferred:
        cost -= 1_000
    if start in signals.clause:
        cost -= 100
    if start in signals.preferred:
        cost -= 160

    internal_commas = [position for position in signals.comma if start < position < end]
    cost += 500 * len(internal_commas)
    cost += 250 * sum(start < position < end for position in signals.clause)

    first = group[0]
    final = group[-1]
    if first in _DETERMINERS or first in _PREPOSITIONS:
        cost += 150
    if final in _DETERMINERS:
        cost += 3_000
    if final in _PREPOSITIONS:
        cost += 3_500
    if final in _CONJUNCTIONS:
        cost += 5_000
    if final in _AUXILIARIES:
        cost += 2_500
    if final in _BOUND_AUXILIARY_FORMS or final == "not":
        cost += 4_000

    if end < len(keys):
        next_key = keys[end]
        if _looks_numeric(final) or _looks_numeric(next_key):
            if final in _PREPOSITIONS or next_key in {"days", "years", "percent", "%"}:
                cost += 850
        if _looks_numeric(final) and next_key in _PREPOSITIONS:
            cost += 2_000
        if (
            _looks_numeric(next_key)
            and end + 1 < len(keys)
            and keys[end + 1] in {"days", "years", "percent", "%"}
        ):
            cost += 2_500
        if next_key in _PREPOSITIONS:
            cost += 1_600
        if next_key in _AUXILIARIES and final.endswith("ly"):
            cost += 1_500
        if next_key in _AUXILIARIES or next_key in _BOUND_AUXILIARY_FORMS:
            cost += 2_000
        if _title_word(exact_words[end - 1]) and _title_word(exact_words[end]):
            cost += 5_000
        if (
            _title_word(exact_words[end])
            and end + 1 < len(exact_words)
            and _title_word(exact_words[end + 1])
        ):
            cost += 4_000
    if final in _PRONOUNS:
        cost += 1_000
    if end < len(keys) and end in signals.grammar.syntax.discouraged_boundaries:
        cost += 8_000
    if end < len(keys) and end in signals.grammar.protected:
        cost += 1_000_000
    return cost


def _looks_numeric(value: str) -> bool:
    return any(character.isdigit() for character in value)


def _title_word(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped and stripped[0].isupper() and _WORDISH.search(stripped))


# Historical v2 exports used these names. They intentionally remain isolated
# from the v3 production chunker.
def dramatic_anchor_ranges(keys: Sequence[str]) -> tuple[tuple[int, int], ...]:
    return ()


def candidate_respects_anchors(
    start: int, end: int, anchors: Sequence[tuple[int, int]]
) -> bool:
    return True


def crosses_hard_boundary(
    start: int, end: int, boundaries: frozenset[int]
) -> bool:
    return crosses_boundary(start, end, boundaries)
