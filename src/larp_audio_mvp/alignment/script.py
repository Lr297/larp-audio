"""Byte-preserving UTF-8 script ingestion."""

from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

from larp_audio_mvp.core.contracts import ScriptDocument
from larp_audio_mvp.core.errors import ScriptReadError


def read_script(source: Path) -> ScriptDocument:
    """Read UTF-8 bytes without universal-newline conversion.

    The optional UTF-8 BOM is metadata rather than script content. SHA-256 is
    calculated over the exact source bytes, including a BOM when present.
    """

    path = source.expanduser().resolve()
    if not path.exists():
        raise ScriptReadError(
            f"script file does not exist: {path.name}", code="SCRIPT_NOT_FOUND"
        )
    if not path.is_file():
        raise ScriptReadError(
            f"script path is not a file: {path.name}", code="SCRIPT_NOT_FILE"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ScriptReadError(
            f"cannot read script: {path.name}", code="SCRIPT_READ_FAILED"
        ) from exc

    has_bom = raw.startswith(codecs.BOM_UTF8)
    content = raw[len(codecs.BOM_UTF8) :] if has_bom else raw
    try:
        exact_text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ScriptReadError(
            "script must be valid UTF-8", code="SCRIPT_INVALID_UTF8"
        ) from exc
    if not exact_text:
        raise ScriptReadError("script is empty", code="SCRIPT_EMPTY")
    if exact_text.isspace():
        raise ScriptReadError(
            "script contains only whitespace", code="SCRIPT_WHITESPACE_ONLY"
        )

    return ScriptDocument(
        exact_text=exact_text,
        source_path=path,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        encoding="utf-8",
        has_bom=has_bom,
        character_count=len(exact_text),
        line_count=count_script_lines(exact_text),
    )


def count_script_lines(text: str) -> int:
    """Count logical lines without changing CRLF, LF, or CR separators."""

    if not text:
        return 0
    index = 0
    separators = 0
    while index < len(text):
        if text[index] == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
            separators += 1
            index += 2
        elif text[index] in ("\r", "\n"):
            separators += 1
            index += 1
        else:
            index += 1
    return separators + 1
