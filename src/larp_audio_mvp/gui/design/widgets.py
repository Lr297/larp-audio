"""Reusable editorial widgets for the approved production GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .tokens import PRIMARY_RED


def _label(text: str, object_name: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    return widget


class Hairline(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hairline")


class WaveformIcon(QWidget):
    """Small dependency-free waveform mark; decorative only."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(46, 46)
        self.setAccessibleName("Audio waveform")

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(PRIMARY_RED), 2))
        for index, height in enumerate((10, 22, 34, 18, 28, 12)):
            x = 7 + index * 6
            painter.drawLine(x, 23 - height // 2, x, 23 + height // 2)


class SurfaceCard(QFrame):
    def __init__(
        self,
        title: str,
        helper: str = "",
        *,
        kicker: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("surfaceCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 17, 20, 16)
        self.body.setSpacing(9)
        if kicker:
            self.body.addWidget(_label(kicker.upper(), "kicker"))
        heading = _label(title, "displayTitle")
        self.body.addWidget(heading)
        if helper:
            caption = _label(helper, "muted")
            caption.setWordWrap(True)
            self.body.addWidget(caption)


class StatusBadge(QWidget):
    """Compact local-processing status used in the header."""

    def __init__(self, text: str = "LOCAL\nPROCESSING", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        dot = _label("●", "kicker")
        dot.setFixedWidth(12)
        self.text_label = _label(text, "statusText")
        layout.addWidget(dot)
        layout.addWidget(self.text_label)

    def setText(self, text: str) -> None:  # noqa: N802 - QLabel-compatible API
        self.text_label.setText(text.upper())

    def text(self) -> str:
        return self.text_label.text()


class MainHeader(QWidget):
    def __init__(
        self,
        start_over_button: QWidget,
        advanced_button: QWidget,
        about_button: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(12)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        copy.addWidget(_label("LARP AUDIO", "productTitle"))
        copy.addWidget(_label("Voiceover and exact script into timed subtitles.", "productStatement"))
        self.status_badge = StatusBadge()
        layout.addLayout(copy, 1)
        layout.addWidget(self.status_badge)
        layout.addSpacing(12)
        layout.addWidget(start_over_button)
        layout.addWidget(advanced_button)
        layout.addWidget(about_button)


class WorkflowStrip(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("AUDIO   /   SCRIPT   /   PROCESS   /   REVIEW", parent)
        self.setObjectName("workflowStrip")
        self.setAlignment(Qt.AlignCenter)


class EditorialPauseChoice(QFrame):
    """Numbered pause option with a real accessible QPushButton hit target."""

    def __init__(
        self,
        number: str,
        name: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pauseChoice")
        self.setAttribute(Qt.WA_Hover, True)
        self.setProperty("selected", False)
        self.setMinimumHeight(78)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(13)
        self.number = _label(number, "pauseNumber")
        self.name = _label(name.upper(), "pauseName")
        self.description = _label(description, "pauseDescription")
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(self.name)
        copy.addWidget(self.description)
        copy.addStretch(1)
        row.addWidget(self.number)
        row.addLayout(copy, 1)
        self.button = QPushButton(self)
        self.button.setObjectName("pauseOverlay")
        self.button.setCheckable(True)
        self.button.setText("")
        self.button.setAccessibleName(f"{name} pause style")
        self.button.toggled.connect(self._set_selected)
        self.button.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.button.setGeometry(self.rect())
        self.button.raise_()

    def _set_selected(self, selected: bool) -> None:
        for widget in (self, self.number, self.name):
            widget.setProperty("selected", selected)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()
