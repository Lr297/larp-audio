"""Resolve immutable resources in source and PyInstaller-frozen layouts."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class BundledResourceResolver:
    resource_root: Path
    platform_key: str
    frozen: bool
    developer_mode: bool = False

    @classmethod
    def current(cls, *, developer_mode: bool = False) -> "BundledResourceResolver":
        frozen = bool(getattr(sys, "frozen", False))
        if frozen:
            root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        else:
            root = Path(__file__).resolve().parents[3] / "resources"
        if sys.platform == "darwin":
            platform_key = "macos-arm64" if os.uname().machine == "arm64" else "macos-x86_64"
        elif sys.platform.startswith("win"):
            platform_key = "windows-x86_64"
        else:
            platform_key = "linux-x86_64"
        return cls(root, platform_key, frozen, developer_mode)

    @property
    def media_directory(self) -> Path:
        return self.resource_root / "bin" / self.platform_key

    def media_tool(self, name: str, *, explicit: Path | None = None) -> Path:
        executable_name = f"{name}.exe" if self.platform_key.startswith("windows") else name
        bundled = self.media_directory / executable_name
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return bundled
        if self.developer_mode and explicit is not None and explicit.is_file():
            return explicit
        if not self.frozen and self.developer_mode:
            system = shutil.which(executable_name)
            if system:
                return Path(system)
        raise ConfigurationError(
            f"Required bundled media component is unavailable: {name}. "
            "Reinstall LARP Audio or use Repair in Advanced Settings."
        )

    def assert_packaged_resources(self) -> tuple[Path, Path]:
        return self.media_tool("ffmpeg"), self.media_tool("ffprobe")
