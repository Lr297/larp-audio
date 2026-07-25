from __future__ import annotations

import os
from pathlib import Path

import pytest

from larp_audio_mvp.audio.executables import ExecutableResolver
from larp_audio_mvp.core.errors import ExecutableNotFoundError


def _executable(directory: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    path = directory / f"{name}{suffix}"
    path.write_text("tool", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_explicit_executable_has_priority(tmp_path: Path) -> None:
    explicit = _executable(tmp_path, "ffprobe")
    resolver = ExecutableResolver(ffprobe_path=explicit, path_environment="")

    assert resolver.resolve("ffprobe") == explicit.resolve()


def test_invalid_explicit_executable_is_actionable(tmp_path: Path) -> None:
    missing = tmp_path / "missing ffprobe"
    resolver = ExecutableResolver(ffprobe_path=missing, path_environment="")

    with pytest.raises(ExecutableNotFoundError) as captured:
        resolver.resolve("ffprobe")

    assert captured.value.code == "TOOL_NOT_FOUND"
    assert "ffprobe" in str(captured.value)
    assert str(missing) in str(captured.value)
    assert "paths.ffprobe_path" in str(captured.value)


def test_bundled_directory_is_checked_before_path(tmp_path: Path) -> None:
    bundled = tmp_path / "bundle tools"
    bundled.mkdir()
    executable = _executable(bundled, "ffmpeg")
    resolver = ExecutableResolver(
        bundled_tools_directory=bundled,
        path_environment="",
    )

    assert resolver.resolve("ffmpeg") == executable.resolve()


def test_system_path_is_supported(tmp_path: Path) -> None:
    executable = _executable(tmp_path, "ffmpeg")
    resolver = ExecutableResolver(path_environment=str(tmp_path))

    assert resolver.resolve("ffmpeg") == executable.resolve()
