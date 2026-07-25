"""Context-aware subtitle display text derived from exact script spans."""

from __future__ import annotations

import re

from larp_audio_mvp.subtitles.wrapping import normalize_layout_whitespace

_CLOSING = frozenset("\"'])}»”’")
_ABBREVIATIONS = frozenset(
    {
        "dr",
        "e.g",
        "etc",
        "i.e",
        "jr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "st",
        "vs",
        "г",
        "им",
        "т.д",
        "т.п",
    }
)
_TOKEN_BEFORE_DOT = re.compile(r"([\w.]+)$", re.UNICODE)
_INITIALISM = re.compile(r"(?:[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]\.){2,}$")


def _token_before_period(text: str, period_index: int) -> str:
    match = _TOKEN_BEFORE_DOT.search(text[:period_index])
    return "" if match is None else match.group(1)


def _is_abbreviation_period(text: str, period_index: int) -> bool:
    token = _token_before_period(text, period_index)
    key = token.casefold()
    return key in _ABBREVIATIONS or bool(_INITIALISM.fullmatch(token + "."))


def is_sentence_period_at(text: str, period_index: int) -> bool:
    """Return whether one ASCII dot is a sentence boundary in its source context."""

    if not 0 <= period_index < len(text) or text[period_index] != ".":
        return False
    previous = text[period_index - 1] if period_index else ""
    following = text[period_index + 1] if period_index + 1 < len(text) else ""
    if previous == "." or following == ".":
        return True  # ASCII ellipsis remains visible but is a hard boundary.
    if previous.isdigit() and following.isdigit():
        return False
    if _is_abbreviation_period(text, period_index):
        return False
    cursor = period_index + 1
    while cursor < len(text) and text[cursor] in _CLOSING:
        cursor += 1
    return cursor == len(text) or text[cursor].isspace()


def removable_terminal_period_index(source_text_exact: str) -> int | None:
    """Locate a removable ordinary period at the end of one subtitle span."""

    cursor = len(source_text_exact)
    while cursor and source_text_exact[cursor - 1].isspace():
        cursor -= 1
    while cursor and source_text_exact[cursor - 1] in _CLOSING:
        cursor -= 1
    period_index = cursor - 1
    if period_index < 0 or source_text_exact[period_index] != ".":
        return None
    if period_index and source_text_exact[period_index - 1] == ".":
        return None
    return (
        period_index
        if is_sentence_period_at(source_text_exact, period_index)
        else None
    )


def subtitle_display_text(source_text_exact: str) -> str:
    """Hide commas and terminal periods without mutating the source substring."""

    text = source_text_exact.replace(",", "")
    period_index = removable_terminal_period_index(text)
    if period_index is not None:
        text = text[:period_index] + text[period_index + 1 :]
    return normalize_layout_whitespace(text)


def has_removable_terminal_period(display_text: str) -> bool:
    """Detect a v4-forbidden ordinary terminal period in final display text."""

    return removable_terminal_period_index(display_text) is not None


def removable_terminal_comma_index(source_text_exact: str) -> int | None:
    """Locate one ordinary comma immediately before terminal closers."""

    cursor = len(source_text_exact)
    while cursor and source_text_exact[cursor - 1].isspace():
        cursor -= 1
    while cursor and source_text_exact[cursor - 1] in _CLOSING:
        cursor -= 1
    comma_index = cursor - 1
    return comma_index if comma_index >= 0 and source_text_exact[comma_index] == "," else None


def has_removable_terminal_comma(display_text: str) -> bool:
    return removable_terminal_comma_index(display_text) is not None


def legacy_period_free_display_text(source_text_exact: str) -> str:
    """Reconstruct the Stage 14.2/14.3 display rule for read compatibility."""

    period_index = removable_terminal_period_index(source_text_exact)
    if period_index is None:
        return normalize_layout_whitespace(source_text_exact)
    return normalize_layout_whitespace(
        source_text_exact[:period_index] + source_text_exact[period_index + 1 :]
    )
