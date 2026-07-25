from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from larp_audio_mvp.audio.process import SubprocessRunner
from larp_audio_mvp.core.errors import ProcessExecutionError, ProcessTimeoutError


def test_runner_uses_argument_list_and_shell_false(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    unicode_path = Path("папка с пробелами") / "голос.wav"

    result = SubprocessRunner().run(
        ["ffprobe", str(unicode_path)],
        timeout_seconds=5,
    )

    assert result.stdout == "ok"
    assert observed["arguments"] == ["ffprobe", str(unicode_path)]
    assert observed["shell"] is False
    assert observed["capture_output"] is True
    assert observed["timeout"] == 5


def test_runner_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=0.01)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProcessTimeoutError) as captured:
        SubprocessRunner().run(["ffprobe"], timeout_seconds=0.01)

    assert captured.value.code == "PROCESS_TIMEOUT"


def test_runner_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            arguments,
            3,
            stdout="",
            stderr="broken input",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProcessExecutionError) as captured:
        SubprocessRunner().run(["ffprobe", "input.wav"], timeout_seconds=5)

    assert captured.value.code == "PROCESS_FAILED"
    assert "exit code 3" in str(captured.value)
    assert "broken input" in str(captured.value)

