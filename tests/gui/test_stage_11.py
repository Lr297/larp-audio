from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from larp_audio_mvp.core.errors import PipelineValidationError
from larp_audio_mvp.gui.controller import GuiController, TaskLifecycle
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.state import (
    AudioPreflightRequest,
    AudioPreflightResult,
    GuiPhase,
    format_failure_details,
)
from larp_audio_mvp.pipeline import validate_manifest, validate_package
from tests.pipeline.test_full_pipeline import make_service, write_wav
from tests.pipeline.fakes import audio_info


def _wait(qapp, predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate(): return
        QTest.qWait(5)
    raise AssertionError("GUI condition timed out")


def _model(path: Path) -> Path:
    path.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (path / name).write_bytes(b"synthetic")
    return path


def _accept_audio_preflight(controller: GuiController, path: Path) -> None:
    identity = str(path.resolve()).casefold()
    request = AudioPreflightRequest("test-preflight", path, identity, 1)
    assert controller.begin_audio_preflight(request)
    assert controller.apply_audio_preflight_result(
        AudioPreflightResult(request.request_id, path, identity, audio_info(path))
    )


def test_full_input_controls_and_script_counter(qapp, tmp_path: Path) -> None:
    window = MainWindow(settings=QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat))
    window.show(); qapp.processEvents()
    assert window.browse_audio_button.isVisible()
    assert window.script_editor.isVisible()
    assert window.browse_model_button.isVisible()
    assert not window.process_button.isEnabled()
    audio = tmp_path / "demo.wav"; write_wav(audio)
    output = tmp_path / "output"; output.mkdir()
    model = _model(tmp_path / "model")
    _accept_audio_preflight(window.controller, audio)
    window._set_model_path(model)
    window.controller.set_output_directory(output)
    window.script_editor.setPlainText("Hello exact world.\nПривет, мир!")
    qapp.processEvents()
    assert "5 words" in window.script_counter.text()
    assert window.controller.state.phase is GuiPhase.INPUT_READY
    assert window.process_button.isEnabled()
    window.clear_script()
    assert window.controller.state.script_input is None
    assert not window.process_button.isEnabled()
    window.close()


def test_offscreen_full_pipeline_reaches_success_after_cleanup(qapp, tmp_path: Path) -> None:
    calls: list[str] = []
    controller = GuiController(full_service_factory=lambda request: make_service(calls))
    window = MainWindow(controller=controller, settings=QSettings(str(tmp_path / "full.ini"), QSettings.IniFormat))
    audio = tmp_path / "demo.wav"; write_wav(audio)
    output = tmp_path / "output"; output.mkdir()
    model = _model(tmp_path / "model")
    window.show(); _accept_audio_preflight(window.controller, audio); window._set_model_path(model); window.controller.set_output_directory(output)
    window.script_editor.setPlainText("Hello missing world.\nПривет, мир!")
    qapp.processEvents()
    QTest.mouseClick(window.process_button, Qt.LeftButton)
    assert controller.state.task_active and not window.process_button.isEnabled()
    _wait(qapp, lambda: controller.state.phase is GuiPhase.SUCCESS)
    assert controller.task_lifecycle is TaskLifecycle.IDLE
    assert controller._thread is None and controller._worker is None
    result = controller.state.pipeline_result
    assert result is not None and len(result.subtitle_document.blocks) > 0
    validate_manifest(result.manifest_path, result.final_output_directory)
    validate_package(result.package_zip_path)
    assert window.subtitle_table.model().rowCount() == len(result.subtitle_document.blocks)
    assert window.open_audio_button.isEnabled() and window.open_zip_button.isEnabled()
    window.close()


def test_full_pipeline_failure_is_recoverable_and_copy_is_explicit(qapp, tmp_path: Path) -> None:
    class FailingService:
        def run(self, request, *, progress, cancellation):
            raise PipelineValidationError(
                "Synthetic model preflight failure", code="STT_MODEL_INCOMPLETE"
            )

    controller = GuiController(full_service_factory=lambda _request: FailingService())
    window = MainWindow(
        controller=controller,
        settings=QSettings(str(tmp_path / "failure.ini"), QSettings.IniFormat),
    )
    audio = tmp_path / "demo.wav"; write_wav(audio)
    output = tmp_path / "output"; output.mkdir()
    model = _model(tmp_path / "model")
    window.show()
    _accept_audio_preflight(controller, audio)
    window._set_model_path(model)
    controller.set_output_directory(output)
    window.script_editor.setPlainText("Exact script remains available.")
    clipboard = QApplication.clipboard(); clipboard.setText("unchanged")
    QTest.mouseClick(window.process_button, Qt.LeftButton)
    _wait(qapp, lambda: not controller.state.task_active)
    failure = controller.state.active_failure
    assert failure is not None and failure.error_code == "STT_MODEL_INCOMPLETE"
    assert controller.state.phase is GuiPhase.INPUT_READY
    assert controller.state.script_input is not None
    assert controller.state.script_input.exact_text == "Exact script remains available."
    assert clipboard.text() == "unchanged"
    QTest.mouseClick(window.copy_error_button, Qt.LeftButton)
    assert clipboard.text() == format_failure_details(failure)
    QTest.mouseClick(window.dismiss_error_button, Qt.LeftButton)
    assert controller.state.active_failure is None
    window.close()


def test_audio_preflight_runs_off_thread_and_enables_processing(qapp, tmp_path: Path) -> None:
    audio = tmp_path / "audio with unicode путь.wav"; write_wav(audio)

    class Probe:
        def probe(self, source):
            assert source == audio
            return audio_info(source)

    window = MainWindow(
        settings=QSettings(str(tmp_path / "preflight.ini"), QSettings.IniFormat),
        audio_probe_factory=lambda: Probe(),
    )
    window.show()
    window._start_audio_preflight(audio)
    _wait(qapp, lambda: window._audio_preflight_thread is None)
    assert window.controller.state.audio_preflight_ready is True
    assert "48 kHz" in window.audio_preflight_status.text()
    assert "48000 Hz" in window.audio_preflight_status.toolTip()
    assert "pcm_s16le" in window.audio_preflight_status.toolTip()
    window.close()


def test_gui_pause_and_recognition_controls_feed_project_settings(qapp, tmp_path: Path) -> None:
    captured = []
    controller = GuiController(full_service_factory=lambda request: make_service([]))
    window = MainWindow(controller=controller, settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    audio = tmp_path / "demo.wav"; write_wav(audio)
    output = tmp_path / "output"; output.mkdir()
    model = _model(tmp_path / "model")
    _accept_audio_preflight(controller, audio); window._set_model_path(model); controller.set_output_directory(output)
    window.script_editor.setPlainText("Exact words here")
    window.pause_threshold.setValue(-42.5)
    window.minimum_detected_silence.setValue(350)
    window.minimum_pause_to_shorten.setValue(650)
    window.retained_pause.setValue(250)
    window.maximum_pause_removal.setValue(1_500)
    window.recognition_language.setText("sk")
    window.recognition_beam_size.setValue(7)
    controller.start_full_processing = lambda request: captured.append(request) or True  # type: ignore[method-assign]
    window.start_full_processing()
    request = captured[0]
    assert str(request.pause_settings.silence_threshold_db) == "-42.5"
    assert request.pause_settings.minimum_pause_duration_ms == 350
    assert request.pause_settings.target_remaining_pause_ms == 250
    assert request.recognition_settings.language == "sk"
    assert request.recognition_settings.beam_size == 7
    window.close()
