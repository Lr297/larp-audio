"""Deterministic comparison-only normalization for script-to-ASR matching."""

from __future__ import annotations

import unicodedata

_APOSTROPHES = str.maketrans({
    "’": "'",
    "‘": "'",
    "ʼ": "'",
    "`": "'",
    "´": "'",
    "＇": "'",
})
_HYPHENS = str.maketrans({
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "﹘": "-",
    "﹣": "-",
    "－": "-",
})


def comparison_key(text: str) -> str:
    """Return a matching key without altering or replacing ``text``.

    NFKC and casefold are intentional comparison conveniences. Typographic
    apostrophes and dash variants are unified, while only *outer* punctuation,
    symbols, and whitespace are removed. Internal apostrophes/hyphens remain.
    """

    value = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES)
    value = value.translate(_HYPHENS).casefold()
    start = 0
    end = len(value)
    while start < end and _is_outer_separator(value[start]):
        start += 1
    while end > start and _is_outer_separator(value[end - 1]):
        end -= 1
    return value[start:end]


def structural_key(parts: tuple[str, ...]) -> str:
    """Join comparison keys for a bounded split/merge comparison."""

    return "".join(part.replace("'", "").replace("-", "") for part in parts)


def _is_outer_separator(character: str) -> bool:
    category = unicodedata.category(character)
    return character.isspace() or category.startswith(("P", "S"))
