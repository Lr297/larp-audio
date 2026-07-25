from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import ConfigurationError
from larp_audio_mvp.runtime.paths import default_application_paths, developer_mode_enabled
from larp_audio_mvp.runtime.resources import BundledResourceResolver


def test_default_macos_paths_are_separated(tmp_path: Path) -> None:
    paths = default_application_paths(home=tmp_path, platform="darwin")
    assert paths.data_directory == tmp_path / "Library/Application Support/LARP Audio"
    assert paths.results_directory == tmp_path / "Documents/LARP Audio Results"
    paths.ensure()
    assert paths.results_directory.is_dir()
    assert paths.data_directory not in paths.results_directory.parents


def test_developer_mode_requires_explicit_value() -> None:
    assert developer_mode_enabled({}) is False
    assert developer_mode_enabled({"LARP_AUDIO_DEVELOPER_MODE": "1"}) is True
    assert developer_mode_enabled({"LARP_AUDIO_DEVELOPER_MODE": "true"}) is False


def test_bundled_binary_preferred(tmp_path: Path) -> None:
    tool = tmp_path / "bin/macos-arm64/ffmpeg"
    tool.parent.mkdir(parents=True)
    tool.write_text("binary")
    tool.chmod(0o755)
    resolver = BundledResourceResolver(tmp_path, "macos-arm64", frozen=True)
    assert resolver.media_tool("ffmpeg") == tool


def test_frozen_missing_resource_is_controlled(tmp_path: Path) -> None:
    resolver = BundledResourceResolver(tmp_path, "windows-x86_64", frozen=True)
    with pytest.raises(ConfigurationError, match="Reinstall"):
        resolver.media_tool("ffprobe")


def test_path_fallback_is_development_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = tmp_path / "ffprobe"; candidate.write_text("x"); candidate.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda *_args, **_kwargs: str(candidate))
    with pytest.raises(ConfigurationError):
        BundledResourceResolver(tmp_path, "macos-arm64", frozen=False, developer_mode=False).media_tool("ffprobe")
    assert BundledResourceResolver(tmp_path, "macos-arm64", frozen=False, developer_mode=True).media_tool("ffprobe") == candidate
