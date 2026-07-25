"""Exact, bounded UTF-8 script input handling for GUI and CLI."""

from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

from larp_audio_mvp.alignment import tokenize_script
from larp_audio_mvp.core.contracts import ScriptTokenKind
from larp_audio_mvp.core.errors import ScriptInputError

from .contracts import NewlineStyle, ScriptInput, ScriptSourceKind

DEFAULT_MAX_SCRIPT_CHARACTERS = 500_000


def load_script_input(
    path: Path,
    *,
    source_kind: ScriptSourceKind = ScriptSourceKind.LOADED_FILE,
    max_characters: int = DEFAULT_MAX_SCRIPT_CHARACTERS,
) -> ScriptInput:
    source = path.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise ScriptInputError("Script file does not exist.", code="SCRIPT_INPUT_INVALID")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ScriptInputError("Script file cannot be read.", code="SCRIPT_INPUT_INVALID") from exc
    has_bom = raw.startswith(codecs.BOM_UTF8)
    body = raw[len(codecs.BOM_UTF8) :] if has_bom else raw
    try:
        exact = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ScriptInputError("Script must be valid UTF-8.", code="SCRIPT_ENCODING_INVALID") from exc
    return _build(
        exact,
        source_kind=source_kind,
        source_path=source,
        raw_hash=hashlib.sha256(raw).hexdigest(),
        has_bom=has_bom,
        was_edited=False,
        max_characters=max_characters,
    )


def create_script_input(
    exact_text: str,
    *,
    source_kind: ScriptSourceKind,
    was_edited_in_gui: bool = False,
    max_characters: int = DEFAULT_MAX_SCRIPT_CHARACTERS,
) -> ScriptInput:
    return _build(
        exact_text,
        source_kind=source_kind,
        source_path=None,
        raw_hash=hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
        has_bom=False,
        was_edited=was_edited_in_gui,
        max_characters=max_characters,
    )


def script_input_from_editor(
    editor_text: str,
    previous: ScriptInput | None,
    *,
    user_edited: bool,
    max_characters: int = DEFAULT_MAX_SCRIPT_CHARACTERS,
) -> ScriptInput:
    """Keep file CRLF/BOM provenance until a real user edit is reported."""
    if previous is not None and not user_edited:
        return previous
    kind = ScriptSourceKind.TYPED if previous is None else previous.source_kind
    return create_script_input(
        editor_text,
        source_kind=kind,
        was_edited_in_gui=user_edited,
        max_characters=max_characters,
    )


def _build(
    exact_text: str,
    *,
    source_kind: ScriptSourceKind,
    source_path: Path | None,
    raw_hash: str,
    has_bom: bool,
    was_edited: bool,
    max_characters: int,
) -> ScriptInput:
    if not exact_text:
        raise ScriptInputError("Original script is empty.", code="SCRIPT_EMPTY")
    if exact_text.isspace():
        raise ScriptInputError("Original script contains only whitespace.", code="SCRIPT_EMPTY")
    if len(exact_text) > max_characters:
        raise ScriptInputError(
            f"Original script exceeds the {max_characters} character limit.",
            code="SCRIPT_TOO_LARGE",
        )
    tokens = tokenize_script(exact_text)
    words = sum(token.kind is ScriptTokenKind.WORD for token in tokens)
    if words == 0:
        raise ScriptInputError("Original script contains no words.", code="SCRIPT_EMPTY")
    return ScriptInput(
        exact_text=exact_text,
        source_kind=source_kind,
        source_path=source_path,
        encoding="utf-8",
        newline_style=_newline_style(exact_text),
        character_count=len(exact_text),
        visible_character_count=sum(not character.isspace() for character in exact_text),
        script_word_count=words,
        sha256=raw_hash,
        was_edited_in_gui=was_edited,
        has_bom=has_bom,
    )


def _newline_style(text: str) -> NewlineStyle:
    styles: set[NewlineStyle] = set()
    without_crlf = text.replace("\r\n", "")
    if "\r\n" in text:
        styles.add(NewlineStyle.CRLF)
    if "\n" in without_crlf:
        styles.add(NewlineStyle.LF)
    if "\r" in without_crlf:
        styles.add(NewlineStyle.CR)
    if "\u2028" in text or "\u2029" in text or "\u0085" in text:
        styles.add(NewlineStyle.UNICODE)
    if not styles:
        return NewlineStyle.NONE
    return next(iter(styles)) if len(styles) == 1 else NewlineStyle.MIXED
