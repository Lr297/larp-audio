from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from larp_audio_mvp.exports import validate_srt_file
from larp_audio_mvp.core.errors import DesktopActionError
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.state import GuiPhase
from larp_audio_mvp.subtitles import read_subtitle_document

pytestmark = pytest.mark.integration


class FakeDesktop:
    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.fail = False

    def open_path(self, path: Path) -> None:
        if self.fail:
            raise DesktopActionError("synthetic desktop failure", code="DESKTOP_TEST")
        self.opened.append(path)

    @staticmethod
    def copy_path(path: Path, clipboard) -> None:
        clipboard.setText(str(path.resolve(strict=False)))


def _wait(qapp, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("GUI condition timed out")


def test_gui_real_backend_generates_valid_pair(qapp, tmp_path: Path) -> None:
    alignment = Path("examples/stage_9_1_example_alignment.json").resolve()
    before = hashlib.sha256(alignment.read_bytes()).hexdigest()
    output = tmp_path / "gui-output"
    desktop = FakeDesktop()
    window = MainWindow(
        settings=QSettings(str(tmp_path / "gui.ini"), QSettings.IniFormat),
        desktop=desktop,  # type: ignore[arg-type]
    )
    window.show()
    window.controller.load_alignment(alignment)
    window.controller.set_output_directory(output)
    QTest.mouseClick(window.generate_button, Qt.LeftButton)
    assert window.controller.state.phase is GuiPhase.PROCESSING
    assert not window.generate_button.isEnabled()
    assert not window.browse_alignment_button.isEnabled()
    assert not window.controller.generate(window.subtitle_settings())
    window.close()
    assert window.isVisible(), "close must be deferred while the worker is active"
    _wait(qapp, lambda: window.controller.state.phase is GuiPhase.SUCCESS)
    blocks = output / "subtitle_blocks.json"
    srt = output / "subtitles.srt"
    document = read_subtitle_document(blocks)
    validate_srt_file(srt, document)
    assert window.subtitle_table.model().rowCount() == len(document.blocks)
    assert window.success_banner.isVisible()
    QTest.mouseClick(window.open_folder_button, Qt.LeftButton)
    assert desktop.opened == [output]
    QTest.mouseClick(window.copy_srt_button, Qt.LeftButton)
    assert QApplication.clipboard().text() == str(srt.resolve())
    window.subtitle_table.setCurrentIndex(window.warning_proxy.index(0, 4))
    window.copy_selected_text()
    assert QApplication.clipboard().text() == document.blocks[0].display_text
    assert window.generate_button.isEnabled()
    desktop.fail = True
    QTest.mouseClick(window.open_folder_button, Qt.LeftButton)
    assert window.controller.state.phase is GuiPhase.SUCCESS
    assert window.controller.state.active_failure is not None
    assert window.subtitle_table.model().rowCount() == len(document.blocks)
    QTest.mouseClick(window.copy_error_button, Qt.LeftButton)
    assert "Code: DESKTOP_TEST" in QApplication.clipboard().text()
    QTest.mouseClick(window.dismiss_error_button, Qt.LeftButton)
    assert window.controller.state.phase is GuiPhase.SUCCESS
    assert window.controller.state.active_failure is None
    assert hashlib.sha256(alignment.read_bytes()).hexdigest() == before
    assert not list(tmp_path.rglob("*.partial.*"))
    assert window.controller.wait_for_worker()
    window.close()


def test_gui_invalid_parent_becomes_error_and_controls_recover(qapp, tmp_path: Path) -> None:
    alignment = Path("examples/stage_9_1_example_alignment.json").resolve()
    parent = tmp_path / "parent-file"
    parent.write_text("file", encoding="utf-8")
    window = MainWindow(
        settings=QSettings(str(tmp_path / "error.ini"), QSettings.IniFormat)
    )
    window.show()
    window.controller.load_alignment(alignment)
    window.controller.set_output_directory(parent / "child")
    QTest.mouseClick(window.generate_button, Qt.LeftButton)
    _wait(qapp, lambda: window.controller.state.active_failure is not None)
    assert window.controller.state.phase is GuiPhase.READY
    assert window.controller.state.failure is not None
    assert window.controller.state.failure.code == "SUBTITLE_OUTPUT_PARENT_INVALID"
    assert window.browse_alignment_button.isEnabled()
    assert window.controller.wait_for_worker()
    window.close()


def test_gui_output_collision_preserves_alignment(qapp, tmp_path: Path) -> None:
    directory = tmp_path / "collision"
    directory.mkdir()
    alignment = directory / "subtitle_blocks.json"
    alignment.write_bytes(Path("examples/stage_9_1_example_alignment.json").read_bytes())
    before = alignment.read_bytes()
    window = MainWindow(
        settings=QSettings(str(tmp_path / "collision.ini"), QSettings.IniFormat)
    )
    window.show()
    window.controller.load_alignment(alignment)
    window.controller.set_output_directory(directory)
    QTest.mouseClick(window.generate_button, Qt.LeftButton)
    _wait(qapp, lambda: window.controller.state.active_failure is not None)
    assert window.controller.state.phase is GuiPhase.READY
    assert window.controller.state.failure is not None
    assert window.controller.state.failure.code == "SUBTITLE_OUTPUT_COLLISION"
    assert alignment.read_bytes() == before
    assert not (directory / "subtitles.srt").exists()
    assert window.controller.wait_for_worker()
    window.close()


def test_gui_corrupt_alignment_is_recoverable_without_worker(qapp, tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{broken", encoding="utf-8")
    window = MainWindow(
        settings=QSettings(str(tmp_path / "corrupt.ini"), QSettings.IniFormat)
    )
    window.show()
    window.controller.load_alignment(corrupt)
    assert window.controller.state.phase is GuiPhase.EMPTY
    assert window.controller.state.failure is not None
    assert window.controller.state.failure.code == "ALIGNMENT_READ_FAILED"
    assert window.browse_alignment_button.isEnabled()
    window.close()
