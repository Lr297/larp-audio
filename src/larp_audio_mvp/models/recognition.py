"""Recognition orchestration and deterministic cleaned-to-original mapping."""

from __future__ import annotations

from fractions import Fraction

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.core.contracts import (
    AudioInfo,
    EditMap,
    RecognitionResult,
    RecognizedWord,
)
from larp_audio_mvp.core.errors import SpeechRecognitionError
from larp_audio_mvp.core.timeline import TimelineMapper
from larp_audio_mvp.models.backend import BackendRecognition, RecognitionBackend
from larp_audio_mvp.models.model_manager import LocalWhisperModelManager


class RecognitionMapper:
    """Quantize backend seconds once, then use the canonical timeline mapper."""

    def map(
        self,
        audio: AudioInfo,
        edit_map: EditMap,
        observed: BackendRecognition,
        *,
        backend_name: str,
        model_name: str,
        model_sha256: str,
        settings: ModelSettings,
    ) -> RecognitionResult:
        total_cleaned = _validate_timelines(audio, edit_map)
        mapper = TimelineMapper(edit_map)
        words: list[RecognizedWord] = []
        for observation in observed.words:
            start_cleaned = _floor_samples(
                observation.start_seconds, audio.sample_rate
            )
            end_cleaned = _ceil_samples(observation.end_seconds, audio.sample_rate)
            if end_cleaned > total_cleaned:
                if end_cleaned - total_cleaned > 1:
                    raise SpeechRecognitionError(
                        "recognized word exceeds cleaned audio duration",
                        code="STT_TIMESTAMP_OUT_OF_BOUNDS",
                    )
                end_cleaned = total_cleaned
            if start_cleaned < 0 or start_cleaned >= end_cleaned:
                raise SpeechRecognitionError(
                    "recognized word has an invalid sample interval",
                    code="STT_INVALID_WORD_TIMESTAMP",
                )
            start_original = mapper.target_to_source(start_cleaned)
            end_original = mapper.target_to_source(end_cleaned)
            words.append(
                RecognizedWord(
                    text=observation.text,
                    sample_rate=audio.sample_rate,
                    start_sample_original=start_original,
                    end_sample_original=end_original,
                    start_sample_cleaned=start_cleaned,
                    end_sample_cleaned=end_cleaned,
                    confidence=observation.confidence,
                )
            )

        metadata = dict(observed.metadata)
        metadata.update(
            {
                "beam_size": str(settings.beam_size),
                "compute_type": settings.compute_type,
                "device": settings.device,
                "model_sha256": model_sha256,
                "temperature": format(settings.temperature, "f"),
                "timestamp_quantization": "floor_start_ceil_end",
                "cleaned_audio_sha256": audio.sha256 or "unavailable",
                "edit_map_output_sha256": edit_map.output_sha256 or "unavailable",
            }
        )
        try:
            return RecognitionResult(
                schema_version="1",
                backend=backend_name,
                model=model_name,
                language=observed.language,
                sample_rate=audio.sample_rate,
                duration_samples_cleaned=total_cleaned,
                duration_samples_original=edit_map.source_total_samples,
                words=tuple(words),
                metadata=tuple(sorted(metadata.items())),
            )
        except (TypeError, ValueError) as exc:
            raise SpeechRecognitionError(
                "recognition timestamps are not monotonic or valid",
                code="STT_INVALID_TIMESTAMPS",
            ) from exc


class LocalSpeechRecognizer:
    """Implement the SpeechRecognizer port without mixing model and mapping."""

    def __init__(
        self,
        *,
        model_manager: LocalWhisperModelManager,
        backend: RecognitionBackend,
        mapper: RecognitionMapper | None = None,
    ) -> None:
        self._model_manager = model_manager
        self._backend = backend
        self._mapper = mapper or RecognitionMapper()

    def recognize(
        self,
        audio: AudioInfo,
        edit_map: EditMap,
        *,
        settings: ModelSettings,
    ) -> RecognitionResult:
        model = self._model_manager.resolve(settings)
        observed = self._backend.transcribe(
            audio.source_path,
            model=model,
            settings=settings,
        )
        return self._mapper.map(
            audio,
            edit_map,
            observed,
            backend_name=settings.whisper_backend,
            model_name=model.name,
            model_sha256=model.sha256,
            settings=settings,
        )


def _validate_timelines(audio: AudioInfo, edit_map: EditMap) -> int:
    if not audio.is_canonical or audio.total_samples is None:
        raise SpeechRecognitionError(
            "speech recognition requires canonical audio with exact samples",
            code="STT_NON_CANONICAL_AUDIO",
        )
    if audio.total_samples != edit_map.output_total_samples:
        raise SpeechRecognitionError(
            "cleaned audio sample count does not match edit map",
            code="STT_EDIT_MAP_DURATION_MISMATCH",
        )
    if audio.sample_rate != edit_map.sample_rate:
        raise SpeechRecognitionError(
            "cleaned audio sample rate does not match edit map",
            code="STT_EDIT_MAP_SAMPLE_RATE_MISMATCH",
        )
    if not edit_map.output_sha256 or audio.sha256 != edit_map.output_sha256:
        raise SpeechRecognitionError(
            "cleaned audio hash does not match edit map",
            code="STT_EDIT_MAP_HASH_MISMATCH",
        )
    return audio.total_samples


def _floor_samples(seconds: Fraction, sample_rate: int) -> int:
    samples = seconds * sample_rate
    return samples.numerator // samples.denominator


def _ceil_samples(seconds: Fraction, sample_rate: int) -> int:
    samples = seconds * sample_rate
    return -(-samples.numerator // samples.denominator)
