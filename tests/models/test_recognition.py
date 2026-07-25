from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.core.contracts import (
    AudioInfo,
    EditKind,
    EditMap,
    EditSpan,
    SampleRange,
)
from larp_audio_mvp.core.errors import SpeechRecognitionError
from larp_audio_mvp.models import (
    BackendRecognition,
    BackendWord,
    LocalSpeechRecognizer,
    LocalWhisperModelManager,
    RecognitionMapper,
)


def _edit_map() -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="test-v1",
        sample_rate=1_000,
        source_total_samples=1_200,
        output_total_samples=1_000,
        source_sha256="source-hash",
        output_sha256="target-hash",
        spans=(
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(0, 400),
                output_range=SampleRange(0, 400),
                reason="keep",
            ),
            EditSpan(
                kind=EditKind.REMOVE,
                source_range=SampleRange(400, 600),
                target_anchor=400,
                candidate_range=SampleRange(300, 700),
                retained_before_samples=100,
                retained_after_samples=100,
                reason="remove",
            ),
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(600, 1_200),
                output_range=SampleRange(400, 1_000),
                reason="keep",
            ),
        ),
    )


def _audio(tmp_path: Path) -> AudioInfo:
    return AudioInfo(
        source_path=tmp_path / "cleaned.wav",
        sample_rate=1_000,
        channels=1,
        sample_format="s16",
        total_samples=1_000,
        sha256="target-hash",
        codec_name="pcm_s16le",
        stream_index=0,
        is_canonical=True,
    )


def test_mapping_quantizes_and_maps_cleaned_to_original(tmp_path: Path) -> None:
    observed = BackendRecognition(
        language="en",
        duration_seconds=Fraction(1, 1),
        words=(
            BackendWord(" before", Fraction(1001, 10_000), Fraction(2, 10)),
            BackendWord(" after", Fraction(2, 5), Fraction(1, 2), 0.9),
        ),
        metadata=(("backend_version", "test"),),
    )

    result = RecognitionMapper().map(
        _audio(tmp_path),
        _edit_map(),
        observed,
        backend_name="faster-whisper",
        model_name="tiny",
        model_sha256="model-hash",
        settings=ModelSettings(whisper_model="tiny"),
    )

    assert result.duration_samples_cleaned == 1_000
    assert result.duration_samples_original == 1_200
    assert result.words[0].start_sample_cleaned == 100
    assert result.words[0].end_sample_cleaned == 200
    assert result.words[0].start_sample_original == 100
    assert result.words[0].end_sample_original == 200
    assert result.words[1].start_sample_cleaned == 400
    assert result.words[1].end_sample_cleaned == 500
    assert result.words[1].start_sample_original == 600
    assert result.words[1].end_sample_original == 700
    assert result.words[1].start_seconds == Fraction(2, 5)
    assert result.words[1].start_seconds_original == Fraction(3, 5)


def test_mapping_rejects_cleaned_hash_mismatch(tmp_path: Path) -> None:
    bad_audio = _audio(tmp_path)
    bad_map = _edit_map()
    object.__setattr__(bad_audio, "sha256", "wrong")

    with pytest.raises(SpeechRecognitionError) as captured:
        RecognitionMapper().map(
            bad_audio,
            bad_map,
            BackendRecognition(language=None, duration_seconds=Fraction(1)),
            backend_name="faster-whisper",
            model_name="tiny",
            model_sha256="model-hash",
            settings=ModelSettings(whisper_model="tiny"),
        )

    assert captured.value.code == "STT_EDIT_MAP_HASH_MISMATCH"


def test_mapping_rejects_out_of_bounds_backend_timestamp(tmp_path: Path) -> None:
    observed = BackendRecognition(
        language="en",
        duration_seconds=Fraction(2),
        words=(BackendWord(" late", Fraction(9, 10), Fraction(11, 10)),),
    )

    with pytest.raises(SpeechRecognitionError) as captured:
        RecognitionMapper().map(
            _audio(tmp_path),
            _edit_map(),
            observed,
            backend_name="faster-whisper",
            model_name="tiny",
            model_sha256="model-hash",
            settings=ModelSettings(whisper_model="tiny"),
        )

    assert captured.value.code == "STT_TIMESTAMP_OUT_OF_BOUNDS"


def test_recognizer_orchestrates_real_preflight_fake_inference_and_mapping(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "tiny"
    model_path.mkdir()
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (model_path / filename).write_bytes(filename.encode("ascii"))

    class FakeBackend:
        model_hash: str | None = None

        def transcribe(self, audio_path: Path, *, model, settings):
            assert audio_path == _audio(tmp_path).source_path
            assert settings.whisper_model == "tiny"
            self.model_hash = model.sha256
            return BackendRecognition(
                language="en",
                duration_seconds=Fraction(1),
                words=(BackendWord(" test", Fraction(1, 10), Fraction(1, 5)),),
            )

    backend = FakeBackend()
    recognizer = LocalSpeechRecognizer(
        model_manager=LocalWhisperModelManager(model_root=tmp_path),
        backend=backend,
    )

    result = recognizer.recognize(
        _audio(tmp_path),
        _edit_map(),
        settings=ModelSettings(whisper_model="tiny"),
    )

    assert backend.model_hash is not None
    assert dict(result.metadata)["model_sha256"] == backend.model_hash
    assert result.words[0].start_sample_cleaned == 100
