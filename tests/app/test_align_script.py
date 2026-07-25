from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.app.align_script import build_parser, main


def test_help_names_required_alignment_inputs() -> None:
    help_text = build_parser().format_help()
    assert "--script" in help_text
    assert "--recognition" in help_text
    assert "--edit-map" in help_text
    assert "--output" in help_text


def test_cli_returns_controlled_error_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--script", str(tmp_path / "missing.txt"),
            "--recognition", str(tmp_path / "missing-recognition.json"),
            "--edit-map", str(tmp_path / "missing-map.json"),
            "--output", str(tmp_path / "alignment.json"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "SCRIPT_NOT_FOUND" in captured.err
    assert "Traceback" not in captured.err
