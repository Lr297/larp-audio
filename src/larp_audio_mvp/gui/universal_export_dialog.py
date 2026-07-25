"""Minimal two-file export dialog with a cooperative QThread lifecycle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from larp_audio_mvp.exports import (
    UniversalExportRequest,
    UniversalExportResult,
    UniversalExportService,
    safe_export_name,
)
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.contracts import PipelineRunResult

from .desktop import DesktopService
from .dialogs import DialogService
from .motion import fade_in_window
from .workers import UniversalExportWorker


class UniversalExportDialog(QDialog):
    lifecycle_finished = Signal(str)

    def __init__(
        self,
        result: PipelineRunResult,
        default_base_name: str,
        preferences: QSettings,
        dialogs: DialogService,
        desktop: DesktopService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setMinimumWidth(600)
        self._result = result
        self._preferences = preferences
        self._dialogs = dialogs
        self._desktop = desktop
        self._thread: QThread | None = None
        self._worker: UniversalExportWorker | None = None
        self._token: CancellationToken | None = None
        self._pending: UniversalExportResult | None = None
        self._failure_details = ""
        self._close_when_finished = False
        self._appearance_animation = None

        layout = QVBoxLayout(self)
        title = QLabel("Export cleaned audio + subtitles")
        title.setObjectName("displayTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Creates one validated WAV and one gapless SRT for CapCut, Premiere, "
            "DaVinci Resolve, Final Cut Pro, and other editors."
        )
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        destination_row = QHBoxLayout()
        default_destination = str(
            preferences.value(
                "last_export_destination", str(result.final_output_directory.parent)
            )
        )
        self.destination = QLineEdit(default_destination)
        self.destination.setReadOnly(True)
        browse = QPushButton("Choose folder")
        browse.clicked.connect(self._choose_destination)
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(browse)
        form.addRow("Destination", destination_row)
        self.base_name = QLineEdit(safe_export_name(default_base_name))
        self.base_name.setPlaceholderText("Export name")
        form.addRow("Export name", self.base_name)
        layout.addLayout(form)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.success_details = QLabel("")
        self.success_details.setWordWrap(True)
        self.success_details.setTextInteractionFlags(
            self.success_details.textInteractionFlags()
            | self.success_details.textInteractionFlags().TextSelectableByMouse
        )
        self.success_details.hide()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.status)
        layout.addWidget(self.success_details)
        layout.addWidget(self.progress)

        actions = QHBoxLayout()
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.hide()
        self.open_folder_button.clicked.connect(self._open_folder)
        self.export_again_button = QPushButton("Export Again")
        self.export_again_button.hide()
        self.export_again_button.clicked.connect(self._reset_after_success)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.request_cancellation)
        self.copy_details_button = QPushButton("Copy details")
        self.copy_details_button.hide()
        self.copy_details_button.clicked.connect(self._copy_failure_details)
        self.close_button = QPushButton("Close")
        self.close_button.hide()
        self.close_button.clicked.connect(self.accept)
        self.export_button = QPushButton("Export")
        self.export_button.setObjectName("primaryAction")
        self.export_button.clicked.connect(self.start_export)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.export_again_button)
        actions.addWidget(self.copy_details_button)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.close_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)

    @property
    def worker_active(self) -> bool:
        return self._thread is not None

    def showEvent(self, event: object) -> None:  # noqa: N802
        super().showEvent(event)
        reduced = bool(self._preferences.value("reduced_motion", False, type=bool))
        self._appearance_animation = fade_in_window(self, reduced_motion=reduced)

    def _choose_destination(self) -> None:
        selected = self._dialogs.choose_output_directory(
            self, Path(self.destination.text())
        )
        if selected is not None:
            self.destination.setText(str(selected.resolve(strict=False)))

    def _request(self) -> UniversalExportRequest:
        document = self._result.subtitle_document
        return UniversalExportRequest(
            destination_folder=Path(self.destination.text()).expanduser().resolve(strict=False),
            base_name=self.base_name.text(),
            cleaned_audio_source=self._result.cleaned_audio_path,
            cleaned_total_samples=self._result.summary.cleaned_duration_samples,
            audio_sample_rate=self._result.summary.sample_rate,
            audio_channel_count=1,
            subtitle_document=document,
        )

    def start_export(self) -> None:
        if self.worker_active:
            return
        token = CancellationToken()
        worker = UniversalExportWorker(self._request(), UniversalExportService(), token)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finished)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker, self._token = thread, worker, token
        self._pending = None
        self._failure_details = ""
        self.copy_details_button.hide()
        self.progress.setRange(0, 0)
        self.export_button.setEnabled(False)
        self.status.setText("Preparing export")
        thread.start()

    def request_cancellation(self) -> None:
        if self._token is not None:
            self._token.request()
            self.status.setText("Stopping safely…")
            self.cancel_button.setEnabled(False)
        else:
            self.reject()

    def request_safe_close(self) -> None:
        self._close_when_finished = True
        self.request_cancellation()

    def _progress(self, message: str) -> None:
        self.status.setText(message)

    def _succeeded(self, result: object) -> None:
        if isinstance(result, UniversalExportResult):
            self._pending = result

    def _failed(self, failure: object) -> None:
        code, message = (
            failure
            if isinstance(failure, tuple) and len(failure) == 2
            else ("EXPORT_FAILED", "Export failed.")
        )
        self.status.setText("Export could not be completed. Your processed result is safe.")
        self._failure_details = f"{code}: {message}"
        self.copy_details_button.show()

    def _cancelled(self) -> None:
        self.status.setText("Export cancelled")

    def _finished(self) -> None:
        thread = self._thread
        if thread is not None and QThread.currentThread() is not thread:
            thread.wait()
        self._thread = None
        self._worker = None
        self._token = None
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if self._pending is not None else 0)
        self.cancel_button.setEnabled(True)
        if self._pending is not None:
            result = self._pending
            self.status.setText("Export complete")
            self.success_details.setText(
                f"Destination: {result.destination_folder}\n"
                f"Audio: {result.audio_path.name}\n"
                f"Subtitles: {result.subtitle_path.name}"
            )
            self.success_details.show()
            self.open_folder_button.show()
            self.export_again_button.show()
            self.close_button.show()
            self.cancel_button.hide()
            self.export_button.hide()
            self._preferences.setValue(
                "last_export_destination", str(result.destination_folder)
            )
        else:
            self.export_button.setEnabled(True)
        self.lifecycle_finished.emit("success" if self._pending is not None else "stopped")
        if self._close_when_finished:
            self.accept()

    def _open_folder(self) -> None:
        if self._pending is not None:
            self._desktop.open_path(self._pending.destination_folder)

    def _copy_failure_details(self) -> None:
        if self._failure_details:
            QApplication.clipboard().setText(self._failure_details)

    def _reset_after_success(self) -> None:
        self._pending = None
        self.status.clear()
        self.success_details.clear()
        self.success_details.hide()
        self.open_folder_button.hide()
        self.export_again_button.hide()
        self.copy_details_button.hide()
        self.close_button.hide()
        self.cancel_button.show()
        self.export_button.show()
        self.export_button.setEnabled(True)

    def reject(self) -> None:
        if self.worker_active:
            self.request_safe_close()
            return
        super().reject()
