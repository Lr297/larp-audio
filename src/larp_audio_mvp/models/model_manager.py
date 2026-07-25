"""Strict preflight for explicitly prepared local Faster-Whisper models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.core.errors import SpeechModelError

_REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


@dataclass(frozen=True, slots=True)
class LocalWhisperModel:
    name: str
    directory: Path
    sha256: str


class LocalWhisperModelManager:
    """Resolve an allowlisted model to a complete local directory only."""

    def __init__(self, *, model_root: Path | None = None) -> None:
        self._model_root = (
            None if model_root is None else model_root.expanduser().resolve()
        )

    def resolve(self, settings: ModelSettings) -> LocalWhisperModel:
        model_name = settings.whisper_model
        if model_name is None:
            raise SpeechModelError(
                "select a local Whisper model: tiny, base, or small",
                code="STT_MODEL_NOT_SELECTED",
            )

        if settings.model_path is not None:
            candidate = settings.model_path.expanduser().resolve()
        elif self._model_root is not None:
            candidate = (self._model_root / model_name).resolve()
        else:
            raise SpeechModelError(
                "no local model path is configured; set models.model_path or "
                "provide a model root",
                code="STT_MODEL_PATH_REQUIRED",
            )

        if not candidate.exists():
            raise SpeechModelError(
                f"local Faster-Whisper {model_name} model was not found; "
                "prepare it manually and configure its directory",
                code="STT_MODEL_NOT_FOUND",
            )
        if not candidate.is_dir():
            raise SpeechModelError(
                "local Faster-Whisper model path must be a directory",
                code="STT_MODEL_NOT_DIRECTORY",
            )
        missing = tuple(
            filename
            for filename in _REQUIRED_MODEL_FILES
            if not (candidate / filename).is_file()
        )
        if missing:
            raise SpeechModelError(
                "local Faster-Whisper model is incomplete; missing: "
                + ", ".join(missing),
                code="STT_MODEL_INCOMPLETE",
            )
        try:
            fingerprint = _model_fingerprint(candidate)
        except OSError as exc:
            raise SpeechModelError(
                "local Faster-Whisper model files cannot be read",
                code="STT_MODEL_READ_FAILED",
            ) from exc
        return LocalWhisperModel(
            name=model_name,
            directory=candidate,
            sha256=fingerprint,
        )


def _model_fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for filename in _REQUIRED_MODEL_FILES:
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        with (directory / filename).open("rb") as model_file:
            while chunk := model_file.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()
