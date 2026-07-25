"""Shared test isolation for process-wide logging state."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from larp_audio_mvp.core.logging import configure_logging


@pytest.fixture(autouse=True)
def _isolate_project_logging() -> None:
    """Bind the project handler to the active pytest capture stream."""

    configure_logging()


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    application = QApplication.instance() or QApplication(["gui-tests"])
    assert isinstance(application, QApplication)
    QCoreApplication.setApplicationName("LARP Audio Tests")
    QCoreApplication.setOrganizationName("LARP Audio Tests")
    return application
