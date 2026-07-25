from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

import pytest

from larp_audio_mvp.alignment import comparison_key, read_script, tokenize_script
from larp_audio_mvp.core.contracts import ScriptTokenKind
from larp_audio_mvp.core.errors import ScriptReadError


def test_tokenizer_reconstructs_spaces_crlf_unicode_and_punctuation() -> None:
    text = "Don’t  A-B, кирилиця — slovenčina!\r\nПривіт 🙂"
    tokens = tokenize_script(text)

    assert "".join(token.exact_text for token in tokens) == text
    assert all(text[token.char_start : token.char_end] == token.exact_text for token in tokens)
    assert [token.token_index for token in tokens] == list(range(len(tokens)))
    assert any(token.exact_text == "  " and token.kind is ScriptTokenKind.WHITESPACE for token in tokens)
    assert any(token.exact_text == "\r\n" for token in tokens)
    assert any(token.exact_text == "Don’t" and token.comparison_key == "don't" for token in tokens)
    assert any(token.exact_text == "A-B" and token.comparison_key == "a-b" for token in tokens)
    assert any(token.exact_text == "🙂" and token.kind is ScriptTokenKind.PUNCTUATION for token in tokens)


def test_script_reader_preserves_crlf_bom_and_exact_byte_hash(tmp_path: Path) -> None:
    raw = codecs.BOM_UTF8 + "Первая\r\nSecond\r\n".encode()
    source = tmp_path / "скрипт с пробелом.txt"
    source.write_bytes(raw)

    document = read_script(source)

    assert document.exact_text == "Первая\r\nSecond\r\n"
    assert document.has_bom is True
    assert document.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert document.character_count == len(document.exact_text)
    assert document.line_count == 3
    assert source.read_bytes() == raw


@pytest.mark.parametrize("content,code", [(b"", "SCRIPT_EMPTY"), (b" \r\n\t", "SCRIPT_WHITESPACE_ONLY")])
def test_script_reader_rejects_empty_or_whitespace_only(
    tmp_path: Path, content: bytes, code: str
) -> None:
    source = tmp_path / "script.txt"
    source.write_bytes(content)

    with pytest.raises(ScriptReadError) as captured:
        read_script(source)

    assert captured.value.code == code


def test_script_reader_rejects_invalid_utf8(tmp_path: Path) -> None:
    source = tmp_path / "script.txt"
    source.write_bytes(b"\xff")
    with pytest.raises(ScriptReadError) as captured:
        read_script(source)
    assert captured.value.code == "SCRIPT_INVALID_UTF8"


def test_comparison_normalization_is_deterministic_and_comparison_only() -> None:
    assert comparison_key("“Don’t”") == "don't"
    assert comparison_key("ПРИВІТ") == "привіт"
    assert comparison_key("A—B") == "a-b"
    assert comparison_key("  Číslo!  ") == "číslo"
