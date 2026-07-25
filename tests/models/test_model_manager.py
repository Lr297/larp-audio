from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.config import ModelSettings
from larp_audio_mvp.core.errors import SpeechModelError
from larp_audio_mvp.models import LocalWhisperModelManager


def test_missing_local_model_has_stable_error(tmp_path: Path) -> None:
    settings = ModelSettings(whisper_model="tiny")

    with pytest.raises(SpeechModelError) as captured:
        LocalWhisperModelManager(model_root=tmp_path).resolve(settings)

    assert captured.value.code == "STT_MODEL_NOT_FOUND"


def test_incomplete_local_model_lists_required_files(tmp_path: Path) -> None:
    model = tmp_path / "base"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    settings = ModelSettings(whisper_model="base")

    with pytest.raises(SpeechModelError) as captured:
        LocalWhisperModelManager(model_root=tmp_path).resolve(settings)

    assert captured.value.code == "STT_MODEL_INCOMPLETE"
    assert "model.bin" in str(captured.value)
    assert "tokenizer.json" in str(captured.value)


def test_explicit_complete_model_directory_is_resolved(tmp_path: Path) -> None:
    model = tmp_path / "model with spaces ü"
    model.mkdir()
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (model / filename).write_bytes(b"test")
    settings = ModelSettings(
        whisper_model="small",
        model_path=model.resolve(),
    )

    resolved = LocalWhisperModelManager().resolve(settings)

    assert resolved.name == "small"
    assert resolved.directory == model.resolve()
    assert len(resolved.sha256) == 64
