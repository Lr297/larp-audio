from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.app.remove_pauses import main


def test_remove_pauses_cli_reports_missing_explicit_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            str(tmp_path / "input.wav"),
            "--work-directory",
            str(tmp_path / "output"),
            "--silence-threshold-db",
            "-50",
            "--minimum-pause-duration-ms",
            "300",
            "--policy-version",
            "test-v1",
            "--minimum-pause-to-shorten-ms",
            "500",
            "--target-remaining-pause-ms",
            "200",
            "--maximum-removed-per-pause-ms",
            "1000",
            "--ffmpeg",
            str(tmp_path / "missing ffmpeg"),
            "--ffprobe",
            str(tmp_path / "missing ffprobe"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error [TOOL_NOT_FOUND]" in captured.err
