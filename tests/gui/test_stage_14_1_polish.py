from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont

from larp_audio_mvp.gui.design.stylesheet import STYLESHEET
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.motion import MOTION_DURATION_MS, fade_in_window
from larp_audio_mvp.gui.preview.widgets import PreviewPanel
from tests.gui.test_preview import FakeMediaBackend


class ScriptDialogs:
    def __init__(self, script: Path) -> None:
        self.script = script

    def choose_script(self, _parent):
        return self.script


def _window(qapp, settings: QSettings) -> MainWindow:
    window = MainWindow(
        settings=settings,
        media_backend_factory=lambda: FakeMediaBackend(),
        developer_mode=True,
    )
    window.show()
    qapp.processEvents()
    return window


def test_subtitle_viewport_wraps_full_unicode_text_at_multiple_sizes(qapp) -> None:
    panel = PreviewPanel()
    panel.show()
    samples = (
        "One concise subtitle.",
        "A two-line subtitle with apostrophes, punctuation — and symbols & numbers 42!",
        "Кириллический текст полностью виден. Українські літери й mixed Latin stay readable.",
        "Very long subtitle " * 45 + "finalwordgjpqy",
    )
    for width, height in ((360, 190), (640, 240), (960, 320)):
        panel.resize(width, height)
        for subtitle_text in samples:
            panel.cue_viewport.set_text(subtitle_text)
            qapp.processEvents()
            assert panel.cue_label.text() == subtitle_text
            assert panel.cue_label.wordWrap()
            assert panel.cue_viewport.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert panel.cue_viewport.text_fits_render_surface()
            if "finalwordgjpqy" in subtitle_text:
                assert panel.cue_label.text().endswith("finalwordgjpqy")
    panel.close()


def test_subtitle_viewport_reflows_after_cue_change_resize_and_high_dpi_font(qapp) -> None:
    panel = PreviewPanel()
    panel.resize(420, 230)
    panel.show()
    font = QFont(panel.cue_label.font())
    font.setPointSizeF(font.pointSizeF() * 2.0)
    panel.cue_label.setFont(font)
    panel.cue_viewport.set_text("TOP Glyphs ÁÉÍ — descenders gypqj in a wrapped subtitle " * 5)
    qapp.processEvents()
    first_height = panel.cue_label.height()
    assert panel.cue_viewport.text_fits_render_surface()
    panel.cue_viewport.set_text("Short cue")
    panel.resize(820, 300)
    qapp.processEvents()
    assert panel.cue_viewport.text_fits_render_surface()
    assert panel.cue_label.height() <= max(first_height, panel.cue_viewport.viewport().height())
    panel.close()


def test_subtitle_viewport_preserves_explicit_two_line_layout_on_resize(qapp) -> None:
    from larp_audio_mvp.gui.preview.widgets import SubtitleViewport

    viewport = SubtitleViewport()
    viewport.resize(640, 160)
    viewport.set_text("Pills can hush my alarms\nfor a while")
    viewport.show()
    qapp.processEvents()
    assert viewport.label.text().splitlines() == [
        "Pills can hush my alarms",
        "for a while",
    ]
    assert viewport.text_fits_render_surface()
    viewport.resize(420, 130)
    qapp.processEvents()
    assert viewport.text_fits_render_surface()
    viewport.close()


def test_script_autosave_restart_start_over_and_clear(qapp, tmp_path: Path) -> None:
    settings_path = tmp_path / "persist.ini"
    settings = QSettings(str(settings_path), QSettings.IniFormat)
    script_text = "Первая строка — exact.\nSecond line: O'Brien & 😀"
    first = _window(qapp, settings)
    first.script_editor.setPlainText(script_text)
    assert first._script_autosave_timer.isActive()
    first._script_autosave_timer.stop()
    first._persist_script()
    first.close()
    qapp.processEvents()

    second = _window(qapp, QSettings(str(settings_path), QSettings.IniFormat))
    assert second.script_editor.toPlainText() == script_text
    assert second.controller.state.script_input is not None
    second.start_over()
    assert second.script_editor.toPlainText() == script_text
    assert second.controller.state.script_input.exact_text == script_text
    second.clear_script()
    second.close()

    third = _window(qapp, QSettings(str(settings_path), QSettings.IniFormat))
    assert third.script_editor.toPlainText() == ""
    assert third.controller.state.script_input is None
    third.close()


def test_close_saves_immediately_and_corrupt_setting_falls_back(qapp, tmp_path: Path) -> None:
    path = tmp_path / "close.ini"
    settings = QSettings(str(path), QSettings.IniFormat)
    window = _window(qapp, settings)
    long_text = "Unicode žltý текст 😀 " * 2_000
    window.script_editor.setPlainText(long_text)
    window.close()
    restored = QSettings(str(path), QSettings.IniFormat)
    assert restored.value("last_exact_script") == long_text
    restored.setValue("last_exact_script", ["corrupt", "setting"])
    restored.sync()
    fallback = _window(qapp, QSettings(str(path), QSettings.IniFormat))
    assert fallback.script_editor.toPlainText() == ""
    fallback.close()


def test_script_persistence_does_not_log_script(qapp, tmp_path: Path, caplog) -> None:
    secret_fixture = "SYNTHETIC_DO_NOT_LOG_Ж"
    window = _window(
        qapp, QSettings(str(tmp_path / "private.ini"), QSettings.IniFormat)
    )
    with caplog.at_level(logging.DEBUG):
        window.script_editor.setPlainText(secret_fixture)
        window._persist_script()
    assert secret_fixture not in caplog.text
    window.clear_script()
    window.close()


def test_uploaded_script_is_persisted_immediately(qapp, tmp_path: Path) -> None:
    script = tmp_path / "скрипт с пробелами.txt"
    script.write_text("Uploaded exact script — žltý 😀", encoding="utf-8", newline="")
    settings_path = tmp_path / "uploaded.ini"
    settings = QSettings(str(settings_path), QSettings.IniFormat)
    window = MainWindow(
        settings=settings,
        dialogs=ScriptDialogs(script),
        media_backend_factory=lambda: FakeMediaBackend(),
        developer_mode=True,
    )
    window.choose_script()
    assert settings.value("last_exact_script") == "Uploaded exact script — žltý 😀"
    window.close()


def test_minimal_interaction_states_and_reduced_motion(qapp, tmp_path: Path) -> None:
    assert "QPushButton:hover" in STYLESHEET
    assert "QPushButton:pressed" in STYLESHEET
    assert "QPushButton:focus" in STYLESHEET
    assert "QPushButton:disabled" in STYLESHEET
    assert 'dragActive="true"' in STYLESHEET
    assert 'accepted="true"' in STYLESHEET
    assert "QTabBar::tab:hover" in STYLESHEET
    window = _window(
        qapp, QSettings(str(tmp_path / "motion.ini"), QSettings.IniFormat)
    )
    before = window.audio_card.geometry()
    window._set_audio_card_state("dragActive", True)
    qapp.processEvents()
    assert window.audio_card.property("dragActive") is True
    assert window.audio_card.geometry() == before
    window._set_audio_card_state("dragActive", False)
    animation = fade_in_window(window, reduced_motion=False)
    assert animation is not None and animation.duration() == MOTION_DURATION_MS
    assert window.isEnabled()
    assert fade_in_window(window, reduced_motion=True) is None
    window.close()
