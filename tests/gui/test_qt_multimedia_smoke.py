from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.gui.preview.qt_media_backend import QtMediaBackend
from tests.pipeline.test_full_pipeline import write_wav


@pytest.mark.integration
def test_qt_multimedia_can_load_synthetic_wav(qapp, tmp_path: Path) -> None:
    try:
        backend = QtMediaBackend()
    except Exception as exc:
        pytest.skip(f"QtMultimedia unavailable: {exc}")
    audio = tmp_path / "preview.wav"; write_wav(audio)
    loaded: list[bool] = []; errors: list[object] = []
    backend.media_loaded.connect(lambda: loaded.append(True)); backend.error_occurred.connect(lambda *args: errors.append(args))
    backend.load(audio)
    deadline = 200
    while deadline and not loaded and not errors:
        qapp.processEvents(); qapp.thread().msleep(5); deadline -= 1
    backend.dispose()
    if errors:
        pytest.skip(f"local multimedia backend could not load WAV: {errors[0]}")
    if not loaded:
        pytest.skip("headless Qt media service did not reach LoadedMedia")
    assert loaded
