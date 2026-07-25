"""Single-action first-launch speech-engine preparation UI."""

from __future__ import annotations

import threading
from enum import Enum

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from larp_audio_mvp.speech_engine import EngineProgress, SpeechEngineManager
from larp_audio_mvp.speech_engine.errors import SpeechEngineCancelled


class SetupState(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    READY = "ready"
    FAILED = "failed"
    CLOSING = "closing"


class SpeechEngineWorker(QThread):
    progress_changed = Signal(object)
    prepared = Signal(str)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, manager: SpeechEngineManager, *, repair: bool = False, parent: object | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.repair = repair
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            method = self.manager.repair if self.repair else self.manager.prepare
            path = method(progress=self.progress_changed.emit, cancel_event=self.cancel_event)
        except SpeechEngineCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:  # worker boundary: present controlled copy, never a traceback
            self.failed.emit(str(exc))
        else:
            self.prepared.emit(str(path))

    def cancel(self) -> None:
        self.cancel_event.set()


class SpeechEngineSetupDialog(QDialog):
    engine_ready = Signal(str)
    lifecycle_finished = Signal(str)

    def __init__(self, manager: SpeechEngineManager, parent: object | None = None, *, repair: bool = False) -> None:
        super().__init__(parent)
        self.manager = manager
        self.repair = repair
        self.worker: SpeechEngineWorker | None = None
        self.state = SetupState.IDLE
        self.cancel_requested = False
        self.close_requested = False
        self.terminal_result: SetupState | None = None
        self._prepared_path: str | None = None
        self._failure_message: str | None = None
        self.setWindowIcon(QApplication.windowIcon())
        self.setWindowTitle("Speech engine setup")
        self.setModal(True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        title = QLabel("Prepare speech engine" if not repair else "Repair speech engine")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        self.message = QLabel(
            "LARP Audio needs one local speech component to calculate word timing. "
            "It is downloaded once, verified, and reused. Your audio and script are never uploaded."
        )
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.detail = QLabel("About 465 MB · internet is needed only for setup")
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Not now")
        self.prepare_button = QPushButton("Repair" if repair else "Prepare speech engine")
        self.prepare_button.setObjectName("primaryButton")
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.prepare_button)
        layout.addLayout(actions)
        self.cancel_button.clicked.connect(self._cancel_or_close)
        self.prepare_button.clicked.connect(self._start)

    def _start(self) -> None:
        if self.worker is not None:
            return
        self.cancel_requested = False
        self.close_requested = False
        self.terminal_result = None
        self._prepared_path = None
        self._failure_message = None
        self._set_state(SetupState.CHECKING)
        self.prepare_button.setEnabled(False)
        self.cancel_button.setText("Cancel")
        self.detail.setText("Connecting…")
        worker = SpeechEngineWorker(self.manager, repair=self.repair, parent=self)
        worker.progress_changed.connect(self._progress)
        worker.prepared.connect(self._prepared)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._finished)
        self.worker = worker
        worker.start()

    def _progress(self, value: object) -> None:
        if not isinstance(value, EngineProgress):
            return
        self.progress.setValue(value.percent)
        current = value.current_file or "speech engine"
        stage = {
            "downloading": SetupState.DOWNLOADING,
            "verifying": SetupState.VERIFYING,
            "installing": SetupState.INSTALLING,
        }.get(value.stage, SetupState.CHECKING)
        if self.state is not SetupState.CANCELLING:
            self._set_state(stage)
        self.detail.setText(f"{value.stage.capitalize()} {current} · {value.percent}%")

    def _prepared(self, path: str) -> None:
        self.progress.setValue(100)
        self.detail.setText("Speech engine ready")
        self._prepared_path = path
        self.terminal_result = SetupState.READY
        self._set_state(SetupState.READY)

    def _failed(self, message: str) -> None:
        self._failure_message = message
        self.terminal_result = SetupState.FAILED
        self._set_state(SetupState.FAILED)

    def _cancelled(self, message: str) -> None:
        self.terminal_result = SetupState.CANCELLED
        self._set_state(SetupState.CANCELLED)
        self.message.setText("Setup cancelled")
        self.detail.setText(message or "The download can be resumed later.")

    def _finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.progress_changed.disconnect(self._progress)
            worker.prepared.disconnect(self._prepared)
            worker.failed.disconnect(self._failed)
            worker.cancelled.disconnect(self._cancelled)
            worker.finished.disconnect(self._finished)
            worker.wait(1000)
            worker.deleteLater()
        terminal = self.terminal_result or SetupState.FAILED
        if terminal is SetupState.READY and self._prepared_path is not None:
            self.engine_ready.emit(self._prepared_path)
            self.lifecycle_finished.emit(terminal.value)
            self.accept()
            return
        if self.close_requested:
            self._set_state(SetupState.CLOSING)
            self.lifecycle_finished.emit(terminal.value)
            super().reject()
            return
        if terminal is SetupState.FAILED:
            self.message.setText("Setup could not be completed. Your existing valid engine was preserved.")
            self.detail.setText(self._failure_message or "Setup failed. Retry when ready.")
        self.prepare_button.setText("Retry")
        self.prepare_button.setEnabled(True)
        self.cancel_button.setText("Close")
        self.cancel_button.setEnabled(True)
        self.lifecycle_finished.emit(terminal.value)

    def _cancel_or_close(self) -> None:
        if self.worker is not None:
            self.request_safe_close(close_dialog=False)
        else:
            self.reject()

    def request_safe_close(self, *, close_dialog: bool = True) -> bool:
        """Request cooperative shutdown; return True only when destruction is safe."""
        if self.worker is None:
            if close_dialog:
                super().reject()
            return True
        self.close_requested = self.close_requested or close_dialog
        if not self.cancel_requested:
            self.cancel_requested = True
            self.worker.cancel()
        self._set_state(SetupState.CANCELLING)
        self.message.setText("Finishing the current setup operation safely…" if close_dialog else "Setup cancelled")
        self.detail.setText("Stopping safely…")
        self.prepare_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        return False

    def reject(self) -> None:
        if self.worker is not None:
            self.request_safe_close(close_dialog=True)
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.worker is not None:
            self.request_safe_close(close_dialog=True)
            event.ignore()
            return
        event.accept()

    @property
    def worker_active(self) -> bool:
        return self.worker is not None

    def _set_state(self, state: SetupState) -> None:
        self.state = state
        self.setProperty("setupState", state.value)
