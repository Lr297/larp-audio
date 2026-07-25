"""Small Qt Widgets view for media controls and active subtitle text."""

from __future__ import annotations

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class WrappedSubtitleLabel(QLabel):
    """A word-wrapped label whose vertical hint follows its current width."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        margins = self.contentsMargins()
        usable = max(1, width - margins.left() - margins.right())
        flags = Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignVCenter
        bounds = self.fontMetrics().boundingRect(0, 0, usable, 100_000, flags, self.text())
        # Extra leading protects uppercase tops and font descenders at
        # fractional/high-DPI scale factors.
        return max(
            self.fontMetrics().height() + margins.top() + margins.bottom() + 8,
            bounds.height() + margins.top() + margins.bottom() + 8,
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        width = max(320, self.width())
        return QSize(width, self.heightForWidth(width))


class SubtitleViewport(QScrollArea):
    """Centered subtitle surface that scrolls vertically only as a last resort."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("subtitleViewport")
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidgetResizable(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.setMinimumHeight(116)
        self.label = WrappedSubtitleLabel("Preview unavailable", self)
        self.label.setObjectName("previewCue")
        self.setWidget(self.label)
        QTimer.singleShot(0, self.reflow)

    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self.verticalScrollBar().setValue(0)
        self.label.updateGeometry()
        self.reflow()
        QTimer.singleShot(0, self.reflow)

    def reflow(self) -> None:
        width = max(1, self.viewport().width())
        required = self.label.heightForWidth(width)
        height = max(self.viewport().height(), required)
        self.label.setMinimumSize(0, 0)
        self.label.resize(width, height)
        self.label.updateGeometry()

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.reflow()

    def text_fits_render_surface(self) -> bool:
        """Geometry assertion helper used by GUI regression tests."""

        return self.label.height() >= self.label.heightForWidth(self.label.width())


class PreviewPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        now_playing = QLabel("NOW PLAYING"); now_playing.setObjectName("tertiary"); now_playing.setAlignment(Qt.AlignCenter); layout.addWidget(now_playing)
        self.cue_viewport = SubtitleViewport(self)
        self.cue_label = self.cue_viewport.label
        self.cue_meta = QLabel("Preview will appear after processing")
        self.cue_meta.setObjectName("muted")
        self.cue_meta.setAlignment(Qt.AlignCenter)
        self.warning_badge = QLabel("")
        self.warning_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.cue_viewport, 1); layout.addWidget(self.cue_meta); layout.addWidget(self.warning_badge)
        transport = QHBoxLayout()
        self.previous_button = QPushButton("Previous"); self.play_button = QPushButton("Play"); self.stop_button = QPushButton("Stop"); self.next_button = QPushButton("Next"); self.reload_button = QPushButton("Reload Preview")
        for button, name in ((self.previous_button, "Previous subtitle cue"), (self.play_button, "Play or pause cleaned audio"), (self.stop_button, "Stop cleaned audio preview"), (self.next_button, "Next subtitle cue")):
            button.setAccessibleName(name); transport.addWidget(button)
        layout.addLayout(transport)
        transport.addWidget(self.reload_button)
        seek = QHBoxLayout(); self.current_time = QLabel("00:00.000"); self.seek_slider = QSlider(Qt.Horizontal); self.total_time = QLabel("00:00.000")
        self.seek_slider.setAccessibleName("Cleaned audio position"); self.seek_slider.setToolTip("Seek on the cleaned audio timeline")
        seek.addWidget(self.current_time); seek.addWidget(self.seek_slider, 1); seek.addWidget(self.total_time); layout.addLayout(seek)
        options = QHBoxLayout(); self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(80); self.volume_slider.setAccessibleName("Preview volume")
        self.mute = QCheckBox("Mute"); self.follow = QCheckBox("Follow playback"); self.follow.setChecked(True); self.auto_scroll = QCheckBox("Auto-scroll table"); self.auto_scroll.setChecked(True)
        options.addWidget(QLabel("Volume")); options.addWidget(self.volume_slider); options.addWidget(self.mute); options.addStretch(1); options.addWidget(self.follow); options.addWidget(self.auto_scroll); layout.addLayout(options)
        self.follow.hide()


def format_preview_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds)); hours, remainder = divmod(milliseconds, 3_600_000); minutes, remainder = divmod(remainder, 60_000); seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}" if hours else f"{minutes:02d}:{seconds:02d}.{millis:03d}"
