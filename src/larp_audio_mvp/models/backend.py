"""Backend-neutral immutable observations returned by local STT inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import isfinite
from pathlib import Path
from typing import Protocol

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.models.model_manager import LocalWhisperModel


@dataclass(frozen=True, slots=True)
class BackendWord:
    text: str
    start_seconds: Fraction
    end_seconds: Fraction
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or self.text == "":
            raise ValueError("backend word text must not be empty")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("backend word interval must be positive")
        if self.confidence is not None and (
            not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("backend confidence must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class BackendRecognition:
    language: str | None
    duration_seconds: Fraction
    words: tuple[BackendWord, ...] = field(default_factory=tuple)
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.language is not None and not self.language:
            raise ValueError("backend language must not be empty")
        if self.duration_seconds < 0:
            raise ValueError("backend duration must be non-negative")


class RecognitionBackend(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        model: LocalWhisperModel,
        settings: ModelSettings,
    ) -> BackendRecognition: ...
