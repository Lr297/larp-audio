"""Compatibility entry point for the Stage 12.1 production design system."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .design.stylesheet import STYLESHEET
from .design.tokens import PRIMARY_RED

ACCENT = PRIMARY_RED


def apply_theme(application: QApplication) -> None:
    application.setStyle("Fusion")
    application.setStyleSheet(STYLESHEET)
