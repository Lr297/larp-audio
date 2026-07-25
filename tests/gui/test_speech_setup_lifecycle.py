from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QDialog

from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.speech_setup import SetupState, SpeechEngineSetupDialog
from larp_audio_mvp.runtime import ApplicationPaths
from PySide6.QtCore import QSettings
from larp_audio_mvp.speech_engine import EngineProgress
from larp_audio_mvp.speech_engine.errors import SpeechEngineCancelled


class ControlledManager:
    def __init__(self, tmp_path: Path, *, fail: bool = False) -> None:
        self.path = tmp_path / "engine"
        self.fail = fail
        self.started = False

    def prepare(self, *, progress, cancel_event):
        self.started = True
        progress(EngineProgress("downloading", 1, 10, "model.bin"))
        for _ in range(400):
            if cancel_event.is_set():
                raise SpeechEngineCancelled("Setup cancelled; partial data is resumable.")
            time.sleep(0.001)
        if self.fail:
            raise RuntimeError("controlled failure")
        self.path.mkdir()
        return self.path

    repair = prepare


def wait_until(qapp, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        qapp.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError("Qt condition timed out")
        time.sleep(0.002)
    qapp.processEvents()


def test_cancel_is_neutral_and_worker_is_cleaned(qapp, tmp_path: Path) -> None:
    dialog = SpeechEngineSetupDialog(ControlledManager(tmp_path))  # type: ignore[arg-type]
    outcomes: list[str] = []
    dialog.lifecycle_finished.connect(outcomes.append)
    dialog._start()
    wait_until(qapp, lambda: dialog.state is SetupState.DOWNLOADING)
    dialog._cancel_or_close()
    dialog._cancel_or_close()
    wait_until(qapp, lambda: dialog.worker is None)
    assert dialog.state is SetupState.CANCELLED
    assert dialog.terminal_result is SetupState.CANCELLED
    assert dialog.message.text() == "Setup cancelled"
    assert outcomes == ["cancelled"]
    assert dialog.prepare_button.isEnabled()
    dialog.close()


def test_close_event_waits_for_worker_and_has_no_qthread_warning(qapp, tmp_path: Path) -> None:
    messages: list[str] = []

    def handler(_kind: QtMsgType, _context, message: str) -> None:
        messages.append(message)

    previous = qInstallMessageHandler(handler)
    try:
        dialog = SpeechEngineSetupDialog(ControlledManager(tmp_path))  # type: ignore[arg-type]
        dialog.show()
        dialog._start()
        wait_until(qapp, lambda: dialog.worker_active)
        dialog.close()
        assert dialog.worker_active
        assert dialog.state is SetupState.CANCELLING
        wait_until(qapp, lambda: dialog.worker is None)
        dialog.deleteLater()
        qapp.processEvents()
    finally:
        qInstallMessageHandler(previous)
    assert not any("QThread: Destroyed while thread is still running" in value for value in messages)


def test_escape_uses_same_safe_close_path(qapp, tmp_path: Path) -> None:
    dialog = SpeechEngineSetupDialog(ControlledManager(tmp_path))  # type: ignore[arg-type]
    dialog.show()
    dialog._start()
    wait_until(qapp, lambda: dialog.worker_active)
    dialog.reject()
    assert dialog.close_requested
    assert dialog.state is SetupState.CANCELLING
    wait_until(qapp, lambda: dialog.worker is None)


def test_success_after_previous_cancellation_uses_new_worker(qapp, tmp_path: Path) -> None:
    manager = ControlledManager(tmp_path)
    dialog = SpeechEngineSetupDialog(manager)  # type: ignore[arg-type]
    dialog._start()
    wait_until(qapp, lambda: dialog.worker_active)
    dialog._cancel_or_close()
    wait_until(qapp, lambda: dialog.worker is None)
    assert dialog.state is SetupState.CANCELLED
    dialog._start()
    wait_until(qapp, lambda: dialog.worker is None, timeout=3.0)
    assert dialog.terminal_result is SetupState.READY
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_main_window_close_waits_for_setup_worker(qapp, tmp_path: Path) -> None:
    paths = ApplicationPaths(tmp_path / "data", tmp_path / "results", tmp_path / "logs")
    window = MainWindow(
        settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat),
        application_paths=paths,
        developer_mode=False,
    )
    dialog = SpeechEngineSetupDialog(ControlledManager(tmp_path), window)  # type: ignore[arg-type]
    dialog.lifecycle_finished.connect(window._speech_setup_lifecycle_finished)
    window._speech_setup_dialog = dialog
    window.show()
    dialog.show()
    dialog._start()
    wait_until(qapp, lambda: dialog.worker_active)
    window.close()
    assert window._close_after_speech_setup
    assert dialog.state is SetupState.CANCELLING
    wait_until(qapp, lambda: dialog.worker is None)
    wait_until(qapp, lambda: not window.isVisible())


def test_application_quit_controller_waits_for_setup_worker(qapp, tmp_path: Path) -> None:
    paths = ApplicationPaths(tmp_path / "data", tmp_path / "results", tmp_path / "logs")
    window = MainWindow(
        settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat),
        application_paths=paths,
        developer_mode=False,
    )
    dialog = SpeechEngineSetupDialog(ControlledManager(tmp_path), window)  # type: ignore[arg-type]
    dialog.lifecycle_finished.connect(window._speech_setup_lifecycle_finished)
    window._speech_setup_dialog = dialog
    window.show()
    dialog.show()
    dialog._start()
    wait_until(qapp, lambda: dialog.worker_active)
    window.request_application_quit()
    assert dialog.state is SetupState.CANCELLING
    wait_until(qapp, lambda: dialog.worker is None)
    wait_until(qapp, lambda: not window.isVisible())
