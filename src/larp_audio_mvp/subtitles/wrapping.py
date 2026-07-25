"""Deterministic layout-only whitespace normalization and line wrapping."""

from __future__ import annotations

import re
import unicodedata
from itertools import combinations

from larp_audio_mvp.core.errors import SubtitleChunkingError

_WHITESPACE = re.compile(r"\s+")
_CLOSING_PUNCTUATION = frozenset(",.!?;:%)]}»”’…")
_OPENING_PUNCTUATION = frozenset("([{«“‘")


def non_whitespace_signature(text: str) -> str:
    """Return the exact ordered non-layout content of *text*."""

    return "".join(character for character in text if not character.isspace())


def normalize_layout_whitespace(text: str) -> str:
    """Collapse source whitespace without changing any non-whitespace code point."""

    return _WHITESPACE.sub(" ", text).strip()


def _is_punctuation_only(atom: str) -> bool:
    return bool(atom) and all(
        unicodedata.category(character).startswith("P") for character in atom
    )


def display_atoms(text: str) -> tuple[str, ...]:
    raw = normalize_layout_whitespace(text).split(" ")
    atoms: list[str] = []
    pending_prefix = ""
    for atom in raw:
        if not atom:
            continue
        if _is_punctuation_only(atom):
            if atom[0] in _OPENING_PUNCTUATION:
                pending_prefix += atom
            elif atoms:
                atoms[-1] += atom
            else:
                pending_prefix += atom
            continue
        atoms.append(f"{pending_prefix}{atom}")
        pending_prefix = ""
    if pending_prefix:
        if atoms:
            atoms[-1] += pending_prefix
        else:
            atoms.append(pending_prefix)
    return tuple(atoms)


def _starts_with_closing_punctuation(line: str) -> bool:
    return bool(line) and (
        line[0] in _CLOSING_PUNCTUATION
        or unicodedata.category(line[0]).startswith("P")
        and line[0] not in _OPENING_PUNCTUATION
    )


def wrap_display_lines(
    source_text_exact: str,
    *,
    max_lines: int,
    max_characters_per_line: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Choose a stable balanced wrapping without splitting any display atom."""

    atoms = display_atoms(source_text_exact)
    if not atoms:
        raise SubtitleChunkingError(
            "subtitle display text has no visible content",
            code="EMPTY_SUBTITLE_DISPLAY_TEXT",
        )

    warnings: list[str] = []
    if any(len(atom) > max_characters_per_line for atom in atoms):
        warnings.append(
            "one display atom exceeds max_characters_per_line and was not split"
        )

    best: tuple[tuple[int, int, int, int, tuple[int, ...]], tuple[str, ...]] | None = None
    atom_count = len(atoms)
    for line_count in range(1, min(max_lines, atom_count) + 1):
        for boundaries in combinations(range(1, atom_count), line_count - 1):
            stops = (0, *boundaries, atom_count)
            lines = tuple(
                " ".join(atoms[stops[index] : stops[index + 1]])
                for index in range(line_count)
            )
            lengths = tuple(len(line) for line in lines)
            overflow = tuple(
                max(0, length - max_characters_per_line) for length in lengths
            )
            closing_penalty = sum(
                _starts_with_closing_punctuation(line) for line in lines[1:]
            )
            imbalance = max(lengths) - min(lengths)
            score = (
                max(overflow),
                sum(overflow),
                closing_penalty,
                imbalance,
                boundaries,
            )
            if best is None or score < best[0]:
                best = (score, lines)

    if best is None:
        raise SubtitleChunkingError(
            "subtitle text cannot be wrapped within max_lines",
            code="SUBTITLE_LINE_WRAP_FAILED",
        )
    lines = best[1]
    if any(len(line) > max_characters_per_line for line in lines):
        warnings.append(
            "display layout exceeds max_characters_per_line; exact text was preserved"
        )
    if non_whitespace_signature("\n".join(lines)) != non_whitespace_signature(
        source_text_exact
    ):
        raise SubtitleChunkingError(
            "line wrapping changed non-whitespace source content",
            code="SUBTITLE_TEXT_CHANGED",
        )
    return lines, tuple(warnings)


_NATURAL_LINE_STARTS = frozenset(
    {"after", "and", "at", "before", "because", "but", "by", "during", "for", "from", "if", "in", "of", "on", "or", "so", "to", "when", "while", "with", "without"}
)


def layout_semantic_cue(
    display_text_plain: str,
    *,
    protected_boundaries: frozenset[int] = frozenset(),
    soft_break_threshold: int = 32,
) -> tuple[str, ...]:
    """Select one or two stable visual rows without changing the timed cue."""

    plain = normalize_layout_whitespace(display_text_plain)
    atoms = display_atoms(plain)
    if not atoms:
        raise SubtitleChunkingError("subtitle display text has no visible content", code="EMPTY_SUBTITLE_DISPLAY_TEXT")
    if len(plain) <= soft_break_threshold or len(atoms) < 2:
        return (plain,)
    candidates: list[tuple[tuple[int, int, int, int, int], tuple[str, str]]] = []
    for boundary in range(1, len(atoms)):
        if boundary in protected_boundaries:
            continue
        first = " ".join(atoms[:boundary])
        second = " ".join(atoms[boundary:])
        one_word_tail = int(len(atoms) - boundary == 1)
        one_word_head = int(boundary == 1)
        natural_penalty = int(atoms[boundary].casefold().strip("\"'([{«“‘") not in _NATURAL_LINE_STARTS)
        overflow = max(0, len(first) - 28) + max(0, len(second) - 28)
        imbalance = abs(len(first) - len(second))
        score = (overflow, one_word_head + one_word_tail, natural_penalty, imbalance, boundary)
        candidates.append((score, (first, second)))
    if not candidates:
        return (plain,)
    lines = min(candidates)[1]
    if len(lines[0].split()) == 1 or len(lines[1].split()) == 1:
        return (plain,)
    if " ".join(lines) != plain:
        raise SubtitleChunkingError("line layout changed display text", code="SUBTITLE_TEXT_CHANGED")
    return lines
