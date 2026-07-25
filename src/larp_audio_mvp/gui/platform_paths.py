"""Qt-native platform paths used by the installed desktop application."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths

from larp_audio_mvp.runtime import ApplicationPaths


def qt_application_paths() -> ApplicationPaths:
    data_root = Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "LARP Audio"
    documents = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
    return ApplicationPaths(data_root, documents / "LARP Audio Results", data_root / "logs")
