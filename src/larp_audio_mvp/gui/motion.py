"""Small opt-out animations that never block user input."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QWidget


MOTION_DURATION_MS = 150


def fade_in_window(
    widget: QWidget, *, reduced_motion: bool = False
) -> QPropertyAnimation | None:
    if reduced_motion:
        widget.setWindowOpacity(1.0)
        return None
    animation = QPropertyAnimation(widget, b"windowOpacity", widget)
    animation.setDuration(MOTION_DURATION_MS)
    animation.setStartValue(0.88)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start()
    return animation
