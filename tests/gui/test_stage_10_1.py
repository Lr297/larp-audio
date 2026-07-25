from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from larp_audio_mvp.core.errors import DesktopActionError
from larp_audio_mvp.gui.controller import GuiController, TaskLifecycle
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.models import SubtitleBlockTableModel, WarningFilterProxyModel
from larp_audio_mvp.gui.path_display import ElidedPathLabel
from larp_audio_mvp.gui.state import (
    FailureSource,
    GeneratedResult,
    GuiFailure,
    GuiPhase,
    format_failure_details,
)
from larp_audio_mvp.subtitles import read_subtitle_document
from larp_audio_mvp.subtitles.service import SubtitleGenerationSummary


def _wait(qapp, predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("GUI condition timed out")


def _window(qapp, tmp_path: Path, **kwargs) -> MainWindow:
    window = MainWindow(
        settings=QSettings(str(tmp_path / "stage10-1.ini"), QSettings.IniFormat),
        **kwargs,
    )
    window.show()
    window.controller.load_alignment(Path("examples/stage_9_1_example_alignment.json"))
    qapp.processEvents()
    return window


def _generated(tmp_path: Path) -> GeneratedResult:
    document = read_subtitle_document(Path("examples/stage_9_1_example_subtitle_blocks.json"))
    diagnostics = document.diagnostics
    summary = SubtitleGenerationSummary(
        subtitle_blocks_path=tmp_path / "subtitle_blocks.json",
        srt_path=tmp_path / "subtitles.srt",
        schema_version=document.schema_version,
        block_count=diagnostics.total_blocks,
        script_word_count=diagnostics.total_script_words,
        exported_word_count=diagnostics.exported_script_words,
        unresolved_word_count=diagnostics.unresolved_script_words,
        interpolated_word_count=diagnostics.interpolated_script_words,
        text_coverage=diagnostics.text_coverage,
        timing_coverage=diagnostics.timing_coverage,
        maximum_characters_per_second=diagnostics.maximum_characters_per_second,
        single_word_blocks=diagnostics.single_word_blocks,
        short_blocks=diagnostics.short_blocks,
        average_words_per_block=diagnostics.average_words_per_block,
        output_paths_validated=True,
        existing_outputs_replaced=False,
        rollback_performed=False,
        warnings_count=diagnostics.warnings_count,
        srt_exportable=True,
    )
    return GeneratedResult(summary, document)


class ControlledWorker(QObject):
    started = Signal()
    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.started.emit()
        self.progress.emit("Controlled worker running")


class DummyService:
    def generate(self, **kwargs):
        raise AssertionError("controlled worker must not call service")


class FailingDesktop:
    def open_path(self, path: Path) -> None:
        raise DesktopActionError("Synthetic desktop rejection", code="DESKTOP_TEST")

    @staticmethod
    def copy_path(path: Path, clipboard) -> None:
        clipboard.setText(str(path))


def test_settings_failure_clipboard_copy_and_dismiss(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    clipboard = QApplication.clipboard()
    clipboard.setText("keep-this")
    window.min_duration.setValue(9_000)
    window.max_duration.setValue(1_000)
    window.start_generation()
    failure = window.controller.state.active_failure
    assert failure is not None and failure.source is FailureSource.SETTINGS_VALIDATION
    assert window.controller.state.phase is GuiPhase.READY
    assert clipboard.text() == "keep-this"
    assert window.copy_error_button.isEnabled()
    QTest.mouseClick(window.copy_error_button, Qt.LeftButton)
    assert clipboard.text() == format_failure_details(failure)
    assert "Minimum duration" in clipboard.text()
    QTest.mouseClick(window.dismiss_error_button, Qt.LeftButton)
    assert window.controller.state.active_failure is None
    assert window.controller.state.alignment is not None
    assert not window.copy_error_button.isEnabled()
    window.close()


def test_latest_failure_is_canonical_and_desktop_failure_preserves_success(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path, desktop=FailingDesktop())
    result = _generated(tmp_path)
    window.controller._pending_result = result
    window.controller._thread_finished()
    assert window.controller.state.phase is GuiPhase.SUCCESS
    rows = window.subtitle_table.model().rowCount()
    window.open_output_folder()
    assert window.controller.state.active_failure.code == "DESKTOP_TEST"
    assert window.controller.state.generated_result is result
    assert window.subtitle_table.model().rowCount() == rows
    QTest.mouseClick(window.dismiss_error_button, Qt.LeftButton)
    assert window.controller.state.phase is GuiPhase.SUCCESS
    assert window.controller.state.active_failure is None
    window.close()


def test_worker_success_is_published_only_after_thread_finished(qapp, tmp_path: Path) -> None:
    workers: list[ControlledWorker] = []

    def factory(request, service):
        worker = ControlledWorker()
        workers.append(worker)
        return worker

    controller = GuiController(service_factory=DummyService, worker_factory=factory)  # type: ignore[arg-type]
    controller.load_alignment(Path("examples/stage_9_1_example_alignment.json"))
    window = _window(qapp, tmp_path, controller=controller)
    assert controller.generate(window.subtitle_settings())
    _wait(qapp, lambda: controller.task_lifecycle is TaskLifecycle.RUNNING)
    workers[0].succeeded.emit(_generated(tmp_path))
    _wait(qapp, lambda: controller.state.phase is GuiPhase.FINISHING)
    assert controller.state.task_active and not window.generate_button.isEnabled()
    assert not controller.generate(window.subtitle_settings())
    assert controller.state.active_failure.code == "GUI_TASK_ACTIVE"
    workers[0].finished.emit()
    _wait(qapp, lambda: controller.state.phase is GuiPhase.SUCCESS)
    assert controller.task_lifecycle is TaskLifecycle.IDLE
    assert not controller.has_pending_outcome
    assert window.generate_button.isEnabled()
    assert controller._thread is None and controller._worker is None
    window.close()


def test_warning_filter_is_view_only(qapp) -> None:
    document = read_subtitle_document(Path("examples/stage_9_1_example_subtitle_blocks.json"))
    source = SubtitleBlockTableModel()
    source.set_document(document.blocks, document.sample_rate)
    proxy = WarningFilterProxyModel()
    proxy.setSourceModel(source)
    assert proxy.rowCount() == len(document.blocks)
    proxy.set_warnings_only(True)
    expected = sum(
        bool(b.warnings or b.contains_interpolated_words or b.contains_unresolved_words)
        for b in document.blocks
    )
    assert proxy.rowCount() == expected
    assert source.rowCount() == len(document.blocks)
    proxy.set_warnings_only(False)
    assert proxy.rowCount() == len(document.blocks)


def test_elided_path_keeps_full_tooltip_and_copies_full_path(qapp) -> None:
    label = ElidedPathLabel()
    value = "/very long/папка с пробелами/" + "nested/" * 30 + "alignment.json"
    label.resize(160, 30)
    label.set_path(value)
    label.show()
    qapp.processEvents()
    assert label.toolTip() == value
    assert label.full_path == value
    assert label.text() != value
    label.copy_full_path()
    assert QApplication.clipboard().text() == value
    windows = "C:\\Users\\Demo User\\" + "nested\\" * 30 + "alignment.json"
    label.set_path(windows)
    assert label.toolTip() == windows
    label.close()
