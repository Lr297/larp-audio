"""Elided display for full backend paths."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QContextMenuEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QSizePolicy


class ElidedPathLabel(QLabel):
    def __init__(self, placeholder: str = "Not selected", parent=None) -> None:
        super().__init__(parent)
        self._full_path = ""
        self._display_name_only = False
        self._placeholder = placeholder
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(80)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self._update_text()

    @property
    def full_path(self) -> str:
        return self._full_path

    def set_path(self, path: object | None) -> None:
        self._full_path = "" if path is None else str(path)
        self._display_name_only = False
        self.setToolTip(self._full_path)
        self._update_text()

    def set_path_name(self, path: object | None) -> None:
        """Display only the portable basename while retaining the full tooltip."""
        self._full_path = "" if path is None else str(path)
        self._display_name_only = bool(self._full_path)
        self.setToolTip(self._full_path)
        self._update_text()

    def copy_full_path(self) -> None:
        if self._full_path:
            QApplication.clipboard().setText(self._full_path)

    def _update_text(self) -> None:
        source = (Path(self._full_path).name if self._display_name_only else self._full_path) or self._placeholder
        available = max(20, self.contentsRect().width() - 4)
        self.setText(self.fontMetrics().elidedText(source, Qt.ElideMiddle, available))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_text()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.ApplicationFontChange):
            self._update_text()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = QMenu(self)
        action = QAction("Copy Full Path", menu)
        action.setEnabled(bool(self._full_path))
        action.triggered.connect(self.copy_full_path)
        menu.addAction(action)
        menu.exec(event.globalPos())
