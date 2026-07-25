"""Thin local-only adapter around Faster-Whisper 1.2.x."""

from __future__ import annotations

import importlib
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.core.errors import SpeechBackendError, SpeechRecognitionError
from larp_audio_mvp.core.logging import get_logger
from larp_audio_mvp.models.backend import BackendRecognition, BackendWord
from larp_audio_mvp.models.model_manager import LocalWhisperModel


def _load_faster_whisper() -> Any:
    return importlib.import_module("faster_whisper")


class FasterWhisperInference:
    """Load one explicit local model and collect word timestamp observations."""

    def __init__(
        self, *, module_loader: Callable[[], Any] = _load_faster_whisper
    ) -> None:
        self._module_loader = module_loader
        self._logger = get_logger("models.faster_whisper")

    def transcribe(
        self,
        audio_path: Path,
        *,
        model: LocalWhisperModel,
        settings: ModelSettings,
    ) -> BackendRecognition:
        try:
            runtime = self._module_loader()
        except (ImportError, ModuleNotFoundError) as exc:
            raise SpeechBackendError(
                "faster-whisper runtime is not installed",
                code="STT_BACKEND_UNAVAILABLE",
            ) from exc

        self._logger.info(
            "starting local speech recognition backend=faster-whisper model=%s",
            model.name,
        )
        try:
            whisper_model = runtime.WhisperModel(
                str(model.directory),
                device=settings.device,
                compute_type=settings.compute_type,
                local_files_only=True,
            )
        except Exception as exc:
            raise SpeechBackendError(
                "Faster-Whisper could not load the configured local model",
                code="STT_MODEL_LOAD_FAILED",
            ) from exc

        try:
            segments, info = whisper_model.transcribe(
                str(audio_path),
                language=settings.language,
                task="transcribe",
                beam_size=settings.beam_size,
                temperature=float(settings.temperature),
                condition_on_previous_text=False,
                without_timestamps=False,
                word_timestamps=True,
                vad_filter=False,
            )
            words: list[BackendWord] = []
            for segment in segments:
                segment_words = getattr(segment, "words", None)
                if segment_words is None:
                    raise SpeechBackendError(
                        "Faster-Whisper did not return requested word timestamps",
                        code="STT_WORD_TIMESTAMPS_MISSING",
                    )
                for word in segment_words:
                    words.append(
                        BackendWord(
                            text=word.word,
                            start_seconds=_seconds(word.start, "word start"),
                            end_seconds=_seconds(word.end, "word end"),
                            confidence=_confidence(word.probability),
                        )
                    )
            duration = _seconds(info.duration, "recognition duration")
            language = getattr(info, "language", None)
            metadata = _metadata(runtime, info)
        except SpeechRecognitionError:
            raise
        except Exception as exc:
            raise SpeechBackendError(
                "Faster-Whisper inference failed",
                code="STT_INFERENCE_FAILED",
            ) from exc

        self._logger.info(
            "local speech recognition completed word_count=%d", len(words)
        )
        return BackendRecognition(
            language=language,
            duration_seconds=duration,
            words=tuple(words),
            metadata=metadata,
        )


def _seconds(value: Any, name: str) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("word probability must be numeric")
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("word probability must be in [0, 1]")
    return confidence


def _metadata(runtime: Any, info: Any) -> tuple[tuple[str, str], ...]:
    values = {
        "backend_version": str(getattr(runtime, "__version__", "unknown")),
        "condition_on_previous_text": "false",
        "vad_filter": "false",
        "word_timestamps": "true",
    }
    language_probability = getattr(info, "language_probability", None)
    if language_probability is not None:
        values["language_probability"] = str(language_probability)
    duration_after_vad = getattr(info, "duration_after_vad", None)
    if duration_after_vad is not None:
        values["duration_after_vad_seconds"] = str(duration_after_vad)
    return tuple(sorted(values.items()))
