from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from larp_audio_mvp.gui.controller import GuiController
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.state import GuiPhase


class FakeDialogs:
    def __init__(self, alignment: Path | None = None, output: Path | None = None) -> None:
        self.alignment = alignment
        self.output = output

    def choose_alignment(self, parent):
        return self.alignment

    def choose_output_directory(self, parent, initial):
        return self.output


class FakeDesktop:
    def __init__(self) -> None:
        self.opened: list[Path] = []

    def open_path(self, path: Path) -> None:
        self.opened.append(path)

    @staticmethod
    def copy_path(path: Path, clipboard) -> None:
        clipboard.setText(str(path.resolve(strict=False)))


def _window(qapp: QApplication, tmp_path: Path, **kwargs) -> MainWindow:
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    window = MainWindow(settings=settings, **kwargs)
    window.show()
    qapp.processEvents()
    return window


def test_application_import_has_no_event_loop_side_effect() -> None:
    import larp_audio_mvp.app.desktop as desktop

    assert callable(desktop.main)


def test_empty_state_and_window_constraints(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    assert window.controller.state.phase is GuiPhase.EMPTY
    assert window.empty_hint.isVisible()
    assert not window.generate_button.isEnabled()
    assert window.minimumWidth() == 1100
    assert window.minimumHeight() == 760
    window.close()


def test_responsive_reference_sizes_keep_primary_controls(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    for width, height in ((1100, 760), (1280, 800), (1280, 900), (1440, 900), (1600, 1000)):
        window.resize(width, height)
        qapp.processEvents()
        assert window.browse_audio_button.isVisible()
        assert window.browse_model_button.isVisible()
        assert window.browse_full_output_button.isVisible()
        assert window.process_button.isVisible()
        assert not window.main_scroll_area.horizontalScrollBar().isVisible()
        assert window.empty_hint.isVisible()
    window.close()


def test_browse_loads_valid_alignment_and_exact_script(qapp, tmp_path: Path) -> None:
    source = Path("examples/stage_9_1_example_alignment.json").resolve()
    window = _window(qapp, tmp_path, dialogs=FakeDialogs(alignment=source))
    QTest.mouseClick(window.browse_alignment_button, Qt.LeftButton)
    assert window.controller.state.phase is GuiPhase.READY
    assert window.controller.state.alignment_summary is not None
    assert window.script_preview.toPlainText() == (
        window.controller.state.alignment.script.exact_text.replace("\r\n", "\n")
    )
    assert source.name in window.alignment_value.text()
    assert "subtitle_blocks.json" in window.output_names.text()
    window.close()


def test_corrupt_alignment_enters_recoverable_error(qapp, tmp_path: Path) -> None:
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{bad", encoding="utf-8")
    window = _window(qapp, tmp_path)
    window.controller.load_alignment(corrupt)
    assert window.controller.state.phase is GuiPhase.EMPTY
    assert window.controller.state.active_failure is not None
    assert window.error_frame.isVisible()
    assert "Error [" in window.error_label.text()
    QTest.mouseClick(window.dismiss_error_button, Qt.LeftButton)
    assert window.controller.state.phase is GuiPhase.EMPTY
    assert window.controller.state.active_failure is None
    window.close()


def test_output_dialog_and_restore_defaults(qapp, tmp_path: Path) -> None:
    output = tmp_path / "result"
    window = _window(qapp, tmp_path, dialogs=FakeDialogs(output=output))
    QTest.mouseClick(window.browse_output_button, Qt.LeftButton)
    assert window.controller.state.output_directory == output.resolve()
    window.max_words.setValue(10)
    window.advanced_group.setChecked(True)
    QTest.mouseClick(window.restore_defaults_button, Qt.LeftButton)
    assert window.max_words.value() == 10
    window.close()


def test_drag_and_drop_valid_and_multiple_invalid(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    valid = tmp_path / "audio.mp3"
    valid.write_bytes(b"synthetic-media-placeholder")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(valid))])
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(event)
    assert window.controller.state.source_audio_path == valid.resolve()
    multiple = QMimeData()
    multiple.setUrls([QUrl.fromLocalFile(str(valid)), QUrl.fromLocalFile(str(valid))])
    bad_event = QDropEvent(QPointF(10, 10), Qt.CopyAction, multiple, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(bad_event)
    assert "GUI_DROP_INVALID" in window.error_label.text()
    window.close()


def test_safe_qsettings_restore_does_not_load_alignment(qapp, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "safe.ini"), QSettings.IniFormat)
    settings.setValue("last_output_directory", str(tmp_path / "last-output"))
    settings.setValue("alignment_path", "must-not-be-restored.json")
    settings.sync()
    window = MainWindow(settings=settings, developer_mode=True)
    window.show()
    qapp.processEvents()
    assert window.controller.state.alignment_path is None
    assert window.controller.state.output_directory == tmp_path / "last-output"
    window.close()


def test_keyboard_focus_and_settings_validation(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    window.browse_alignment_button.setFocus()
    QTest.keyClick(window.browse_alignment_button, Qt.Key_Tab)
    assert QApplication.focusWidget() is not None
    window.min_duration.setValue(9_000)
    window.max_duration.setValue(1_000)
    window.start_generation()
    assert "CONFIGURATION_ERROR" in window.error_label.text()
    window.close()
