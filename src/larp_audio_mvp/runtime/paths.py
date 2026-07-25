"""Cross-platform user-writable locations with test injection points."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    data_directory: Path
    results_directory: Path
    logs_directory: Path

    def ensure(self) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.results_directory.mkdir(parents=True, exist_ok=True)
        self.logs_directory.mkdir(parents=True, exist_ok=True)


def developer_mode_enabled(environ: dict[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return values.get("LARP_AUDIO_DEVELOPER_MODE", "").strip() == "1"


def default_application_paths(*, home: Path | None = None, platform: str | None = None) -> ApplicationPaths:
    """Return OS-conventional paths without relying on a Python-only install."""
    home = Path.home() if home is None else Path(home)
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        data = home / "Library" / "Application Support" / "LARP Audio"
    elif platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        data = local / "LARP Audio"
    else:
        data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "larp-audio"
    documents = home / "Documents"
    return ApplicationPaths(data, documents / "LARP Audio Results", data / "logs")
