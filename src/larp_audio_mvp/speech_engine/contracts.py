"""Immutable user-facing speech-engine state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EngineReadiness(StrEnum):
    NOT_INSTALLED = "not_installed"
    READY = "ready"
    DAMAGED = "damaged"


@dataclass(frozen=True, slots=True)
class EngineStatus:
    readiness: EngineReadiness
    model_path: Path | None = None
    installed_version: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class EngineProgress:
    stage: str
    downloaded_bytes: int
    total_bytes: int
    current_file: str | None = None

    @property
    def percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return min(100, self.downloaded_bytes * 100 // self.total_bytes)
