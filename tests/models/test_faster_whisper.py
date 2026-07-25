from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.core.errors import SpeechBackendError
from larp_audio_mvp.models import FasterWhisperInference, LocalWhisperModel


class FakeWhisperModel:
    created: dict[str, object] = {}
    transcribe_options: dict[str, object] = {}

    def __init__(self, path: str, **options: object) -> None:
        self.created = {"path": path, **options}
        type(self).created = self.created

    def transcribe(self, path: str, **options: object):
        type(self).transcribe_options = {"path": path, **options}
        segment = SimpleNamespace(
            words=[
                SimpleNamespace(
                    word=" Hello",
                    start=0.125,
                    end=0.5,
                    probability=0.875,
                )
            ]
        )
        info = SimpleNamespace(
            language="en",
            language_probability=0.99,
            duration=1.25,
            duration_after_vad=1.25,
        )
        return iter([segment]), info


def test_backend_uses_local_only_model_and_word_timestamps(tmp_path: Path) -> None:
    runtime = SimpleNamespace(__version__="1.2.1", WhisperModel=FakeWhisperModel)
    model = LocalWhisperModel("tiny", tmp_path, "model-hash")
    settings = ModelSettings(
        whisper_model="tiny",
        device="cpu",
        compute_type="int8",
        language="en",
        beam_size=3,
    )

    result = FasterWhisperInference(module_loader=lambda: runtime).transcribe(
        tmp_path / "cleaned ü.wav",
        model=model,
        settings=settings,
    )

    assert FakeWhisperModel.created["path"] == str(tmp_path)
    assert FakeWhisperModel.created["local_files_only"] is True
    assert FakeWhisperModel.transcribe_options["word_timestamps"] is True
    assert FakeWhisperModel.transcribe_options["vad_filter"] is False
    assert FakeWhisperModel.transcribe_options["condition_on_previous_text"] is False
    assert result.words[0].text == " Hello"
    assert result.words[0].start_seconds.numerator == 1
    assert result.words[0].start_seconds.denominator == 8
    assert result.words[0].confidence == 0.875


def test_missing_backend_has_stable_error(tmp_path: Path) -> None:
    def missing_runtime():
        raise ModuleNotFoundError("faster_whisper")

    with pytest.raises(SpeechBackendError) as captured:
        FasterWhisperInference(module_loader=missing_runtime).transcribe(
            tmp_path / "cleaned.wav",
            model=LocalWhisperModel("tiny", tmp_path, "model-hash"),
            settings=ModelSettings(whisper_model="tiny"),
        )

    assert captured.value.code == "STT_BACKEND_UNAVAILABLE"


def test_model_load_failure_is_wrapped(tmp_path: Path) -> None:
    class BrokenModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("native load failed")

    runtime = SimpleNamespace(WhisperModel=BrokenModel)
    with pytest.raises(SpeechBackendError) as captured:
        FasterWhisperInference(module_loader=lambda: runtime).transcribe(
            tmp_path / "cleaned.wav",
            model=LocalWhisperModel("tiny", tmp_path, "model-hash"),
            settings=ModelSettings(whisper_model="tiny"),
        )

    assert captured.value.code == "STT_MODEL_LOAD_FAILED"
