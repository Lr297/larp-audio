from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.app.audio_inspect import main


def test_cli_reports_missing_explicit_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"not needed")

    exit_code = main(
        [
            str(source),
            "--work-directory",
            str(tmp_path / "work"),
            "--ffmpeg",
            str(tmp_path / "missing ffmpeg"),
            "--ffprobe",
            str(tmp_path / "missing ffprobe"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error [TOOL_NOT_FOUND]" in captured.err
    assert "ffmpeg was not found" in captured.err
