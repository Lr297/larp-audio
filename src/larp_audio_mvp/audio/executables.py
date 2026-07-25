"""Deterministic FFmpeg/ffprobe executable resolution."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.core.errors import ExecutableNotFoundError


@dataclass(frozen=True, slots=True)
class MediaExecutables:
    ffmpeg: Path
    ffprobe: Path


class ExecutableResolver:
    """Resolve explicit, bundled, then system media tools."""

    def __init__(
        self,
        *,
        ffmpeg_path: Path | None = None,
        ffprobe_path: Path | None = None,
        bundled_tools_directory: Path | None = None,
        path_environment: str | None = None,
        allow_system_path: bool = True,
    ) -> None:
        self._explicit = {"ffmpeg": ffmpeg_path, "ffprobe": ffprobe_path}
        self._bundled_tools_directory = bundled_tools_directory
        self._path_environment = path_environment
        self._allow_system_path = allow_system_path

    def resolve_all(self) -> MediaExecutables:
        return MediaExecutables(
            ffmpeg=self.resolve("ffmpeg"),
            ffprobe=self.resolve("ffprobe"),
        )

    def resolve(self, tool: str) -> Path:
        if tool not in self._explicit:
            raise ValueError(f"unsupported media tool: {tool}")

        explicit = self._explicit[tool]
        if explicit is not None:
            checked = [explicit.expanduser()]
            resolved = self._validate_candidate(checked[0])
            if resolved is not None:
                return resolved
            raise self._not_found(tool, checked)

        checked: list[Path | str] = []
        if self._bundled_tools_directory is not None:
            for filename in self._candidate_names(tool):
                candidate = self._bundled_tools_directory / filename
                checked.append(candidate)
                resolved = self._validate_candidate(candidate)
                if resolved is not None:
                    return resolved

        if self._allow_system_path:
            checked.append(f"PATH:{tool}")
            from_path = shutil.which(tool, path=self._path_environment)
            if from_path is not None:
                resolved = self._validate_candidate(Path(from_path))
                if resolved is not None:
                    return resolved

        raise self._not_found(tool, checked)

    @staticmethod
    def _candidate_names(tool: str) -> tuple[str, ...]:
        return (f"{tool}.exe", tool) if os.name == "nt" else (tool,)

    @staticmethod
    def _validate_candidate(candidate: Path) -> Path | None:
        if not candidate.is_file():
            return None
        if os.name != "nt" and not os.access(candidate, os.X_OK):
            return None
        return candidate.resolve()

    @staticmethod
    def _not_found(
        tool: str, checked: list[Path | str]
    ) -> ExecutableNotFoundError:
        checked_text = ", ".join(str(item) for item in checked)
        return ExecutableNotFoundError(
            f"{tool} was not found. Checked: {checked_text}. "
            f"Install/repair the application media components. Source developers may set paths.{tool}_path in TOML."
        )
