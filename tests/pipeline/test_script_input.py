from __future__ import annotations

import codecs
from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import ScriptInputError
from larp_audio_mvp.pipeline.contracts import NewlineStyle, ScriptSourceKind
from larp_audio_mvp.pipeline.script_input import create_script_input, load_script_input, script_input_from_editor


@pytest.mark.parametrize(
    ("text", "style"),
    [
        ("Hello\nworld", NewlineStyle.LF),
        ("Hello\r\nworld", NewlineStyle.CRLF),
        ("Hello\rworld", NewlineStyle.CR),
        ("Hello\u2028world", NewlineStyle.UNICODE),
        ("Hello\nworld\r\nagain", NewlineStyle.MIXED),
    ],
)
def test_exact_unicode_newline_inputs(text: str, style: NewlineStyle) -> None:
    value = create_script_input(text, source_kind=ScriptSourceKind.PASTED)
    assert value.exact_text == text
    assert value.newline_style is style
    assert value.script_word_count >= 2


def test_utf8_bom_crlf_and_trailing_newline_are_preserved(tmp_path: Path) -> None:
    raw = codecs.BOM_UTF8 + "Привіт, svet! 😀\r\nĎakujem.\r\n".encode()
    path = tmp_path / "script.txt"
    path.write_bytes(raw)
    value = load_script_input(path)
    assert value.has_bom
    assert value.exact_text.endswith("\r\n")
    assert value.newline_style is NewlineStyle.CRLF
    assert value.source_path == path.resolve()


def test_programmatic_editor_display_does_not_replace_exact_crlf(tmp_path: Path) -> None:
    path = tmp_path / "script.txt"
    path.write_bytes(b"One\r\ntwo")
    original = load_script_input(path)
    unchanged = script_input_from_editor("One\ntwo", original, user_edited=False)
    edited = script_input_from_editor("One\ntwo!", original, user_edited=True)
    assert unchanged is original and unchanged.exact_text == "One\r\ntwo"
    assert edited.exact_text == "One\ntwo!" and edited.was_edited_in_gui


@pytest.mark.parametrize("text", ["", " \t\r\n"])
def test_empty_script_is_rejected(text: str) -> None:
    with pytest.raises(ScriptInputError, match="empty|whitespace"):
        create_script_input(text, source_kind=ScriptSourceKind.TYPED)


def test_invalid_encoding_and_limit_are_controlled(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ScriptInputError) as invalid:
        load_script_input(path)
    assert invalid.value.code == "SCRIPT_ENCODING_INVALID"
    with pytest.raises(ScriptInputError) as large:
        create_script_input("word " * 4, source_kind=ScriptSourceKind.STDIN, max_characters=5)
    assert large.value.code == "SCRIPT_TOO_LARGE"


def test_hash_is_deterministic_and_trailing_newline_matters() -> None:
    one = create_script_input("Ahoj svet", source_kind=ScriptSourceKind.TYPED)
    two = create_script_input("Ahoj svet", source_kind=ScriptSourceKind.TYPED)
    three = create_script_input("Ahoj svet\n", source_kind=ScriptSourceKind.TYPED)
    assert one.sha256 == two.sha256
    assert one.sha256 != three.sha256
