"""QApplication construction without import-time side effects."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from larp_audio_mvp.core.logging import configure_logging, get_logger

from .main_window import MainWindow, PRODUCT_NAME
from .theme import apply_theme
from .platform_paths import qt_application_paths
from larp_audio_mvp.speech_engine import EngineReadiness
from larp_audio_mvp.runtime import BundledResourceResolver
from larp_audio_mvp.version import RELEASE_VERSION

ORGANIZATION_NAME = "LARP Audio"


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    application = QApplication(list(argv) if argv is not None else sys.argv)
    application.setApplicationName(PRODUCT_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setApplicationVersion(RELEASE_VERSION)
    icon_path = BundledResourceResolver.current().resource_root / "icons/larp_audio_master.png"
    if icon_path.is_file():
        application.setWindowIcon(QIcon(str(icon_path)))
    apply_theme(application)
    return application


def run(argv: Sequence[str] | None = None) -> int:
    application = create_application(argv)
    paths = qt_application_paths()
    paths.ensure()
    configure_logging(log_file=paths.logs_directory / "larp-audio.log")
    get_logger("gui").info("desktop GUI starting")
    window = MainWindow(application_paths=paths)
    window.show()
    if not window.developer_mode and window.speech_engine_manager.status().readiness is not EngineReadiness.READY:
        QTimer.singleShot(0, window.prepare_speech_engine)
    return application.exec()
