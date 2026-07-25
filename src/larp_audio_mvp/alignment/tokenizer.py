"""Fully reversible, ASR-independent Unicode script tokenizer."""

from __future__ import annotations

import unicodedata

from larp_audio_mvp.alignment.normalizer import comparison_key
from larp_audio_mvp.core.contracts import ScriptToken, ScriptTokenKind
from larp_audio_mvp.core.errors import ScriptTokenizationError

_WORD_CONNECTORS = frozenset(
    "'’‘ʼ`´＇-‐‑‒–—―−﹘﹣－"
)


def tokenize_script(text: str) -> tuple[ScriptToken, ...]:
    """Tokenize while preserving every code point and exact character offset."""

    tokens: list[ScriptToken] = []
    index = 0
    while index < len(text):
        start = index
        character = text[index]
        if character.isspace():
            index += 1
            while index < len(text) and text[index].isspace():
                index += 1
            kind = ScriptTokenKind.WHITESPACE
        elif _is_word_character(character):
            index += 1
            while index < len(text):
                if _is_word_character(text[index]):
                    index += 1
                    continue
                if (
                    text[index] in _WORD_CONNECTORS
                    and index + 1 < len(text)
                    and _is_word_character(text[index - 1])
                    and _is_word_character(text[index + 1])
                ):
                    index += 1
                    continue
                break
            kind = ScriptTokenKind.WORD
        else:
            index += 1
            kind = ScriptTokenKind.PUNCTUATION

        exact = text[start:index]
        key = comparison_key(exact) if kind is ScriptTokenKind.WORD else None
        if kind is ScriptTokenKind.WORD and not key:
            raise ScriptTokenizationError(
                f"word token at character {start} has no comparison key",
                code="SCRIPT_EMPTY_COMPARISON_KEY",
            )
        tokens.append(
            ScriptToken(
                token_index=len(tokens),
                kind=kind,
                exact_text=exact,
                char_start=start,
                char_end=index,
                comparison_key=key,
            )
        )

    if "".join(token.exact_text for token in tokens) != text:
        raise ScriptTokenizationError(
            "tokenizer failed to reconstruct exact script",
            code="SCRIPT_TOKENIZATION_NOT_REVERSIBLE",
        )
    return tuple(tokens)


def _is_word_character(character: str) -> bool:
    category = unicodedata.category(character)
    return character.isalnum() or category.startswith(("L", "M", "N"))
