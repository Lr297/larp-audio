from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel

from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.runtime import ApplicationPaths
from larp_audio_mvp.speech_engine import SpeechEngineManager


def test_consumer_mode_has_automatic_output_and_no_folder_picker(qapp, tmp_path: Path) -> None:
    paths = ApplicationPaths(tmp_path / "data", tmp_path / "Documents/LARP Audio Results", tmp_path / "logs")
    window = MainWindow(
        settings=QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat),
        application_paths=paths,
        speech_engine_manager=SpeechEngineManager(paths.data_directory),
        developer_mode=False,
    )
    assert window.controller.state.output_directory == paths.results_directory
    assert not window.browse_full_output_button.isEnabled()
    assert window.browse_model_button.text() == "PREPARE ENGINE"
    assert "Documents" in window.full_output_value.text()
    assert window.max_words.maximum() == 10
    labels = tuple(
        label.text() for label in window.advanced_dialog.findChildren(QLabel)
    )
    assert not any("Words per block" in label for label in labels)
    window.close()


def test_legacy_subtitle_limit_is_migrated_to_internal_semantic_ceiling(qapp, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "legacy.ini"), QSettings.IniFormat)
    settings.setValue("subtitle_max_words_per_block", 10)
    paths = ApplicationPaths(tmp_path / "data", tmp_path / "results", tmp_path / "logs")
    window = MainWindow(
        settings=settings,
        application_paths=paths,
        speech_engine_manager=SpeechEngineManager(paths.data_directory),
        developer_mode=False,
    )
    assert window.max_words.value() == 10
    assert int(settings.value("subtitle_max_words_per_block")) == 10
    window.close()
