"""Isolated Stage 12.1 visual prototype. It never imports production MainWindow."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parent
REFERENCE_SCREENSHOTS = (
    Path("/var/folders/gn/7rfq8y590bg4wyy_yz7v5k100000gn/T/TemporaryItems/NSIRD_screencaptureui_YEj01x/Снимок экрана 2026-07-20 в 15.45.34.png"),
    Path("/var/folders/gn/7rfq8y590bg4wyy_yz7v5k100000gn/T/TemporaryItems/NSIRD_screencaptureui_9S3aWX/Снимок экрана 2026-07-20 в 15.46.56.png"),
    Path("/var/folders/gn/7rfq8y590bg4wyy_yz7v5k100000gn/T/TemporaryItems/NSIRD_screencaptureui_A2cWdR/Снимок экрана 2026-07-20 в 15.45.50.png"),
)


@dataclass(frozen=True)
class Tokens:
    canvas: str = "#060606"
    surface: str = "#101010"
    elevated: str = "#161616"
    text: str = "#F2F2F2"
    secondary: str = "#CFCFCF"
    muted: str = "#9A9A9A"
    disabled: str = "#555555"
    red: str = "#FF3F3D"
    red_dark: str = "#B3221F"
    red_hover: str = "#FF5A51"
    line: str = "#232323"
    selected: str = "rgba(255, 63, 61, 0.08)"


T = Tokens()


def system_fonts() -> tuple[str, str]:
    available = set(QFontDatabase.families())
    display = next((name for name in ("Arial Black", "Arial Bold", "Arial") if name in available), "Sans Serif")
    body = next((name for name in ("Helvetica Neue", "Helvetica", "Arial") if name in available), "Sans Serif")
    return display, body


def stylesheet(display: str, body: str) -> str:
    return f"""
    QWidget {{ background: {T.canvas}; color: {T.text}; font-family: "{body}"; font-size: 14px; }}
    QLabel {{ background: transparent; }}
    QLabel#brand {{ font-family: "{display}"; font-size: 26px; font-weight: 900; letter-spacing: -0.4px; }}
    QLabel#statement {{ color: {T.muted}; font-size: 12px; }}
    QLabel#nav {{ color: {T.muted}; font-size: 13px; font-weight: 600; letter-spacing: 0.5px; }}
    QLabel#status {{ color: {T.secondary}; font-size: 11px; font-weight: 700; letter-spacing: 1.1px; }}
    QLabel#strip {{ color: #777777; font-size: 10px; font-weight: 700; letter-spacing: 1.8px; padding: 7px 0; }}
    QLabel#kicker {{ color: {T.red}; font-size: 11px; font-weight: 800; letter-spacing: 1.7px; }}
    QLabel#display {{ font-family: "{display}"; font-size: 27px; font-weight: 900; letter-spacing: -0.3px; }}
    QLabel#section {{ font-family: "{display}"; font-size: 18px; font-weight: 900; }}
    QLabel#muted {{ color: {T.muted}; }}
    QLabel#tiny {{ color: {T.muted}; font-size: 11px; letter-spacing: 0.4px; }}
    QLabel#number {{ font-family: "{display}"; color: #343434; font-size: 30px; font-weight: 900; }}
    QLabel#numberActive {{ font-family: "{display}"; color: {T.red}; font-size: 30px; font-weight: 900; }}
    QLabel#cueNumber {{ font-family: "{display}"; color: #444444; font-size: 22px; font-weight: 900; }}
    QLabel#cueNumberActive {{ font-family: "{display}"; color: {T.red}; font-size: 22px; font-weight: 900; }}
    QLabel#metric {{ font-family: "{display}"; color: {T.text}; font-size: 26px; font-weight: 900; }}
    QLabel#metricRed {{ font-family: "{display}"; color: {T.red}; font-size: 26px; font-weight: 900; }}
    QFrame#hairline {{ background: {T.line}; min-height: 1px; max-height: 1px; }}
    QFrame#inputSurface {{ background: {T.surface}; border: 1px solid {T.line}; border-radius: 12px; }}
    QFrame#audioDrop {{ background: transparent; border: 0; }}
    QFrame#pauseChoice {{ background: transparent; border-top: 1px solid {T.line}; border-bottom: 1px solid {T.line}; }}
    QFrame#pauseChoiceActive {{ background: transparent; border-top: 2px solid {T.red}; border-bottom: 1px solid {T.line}; }}
    QFrame#setupBar {{ background: {T.surface}; border-top: 1px solid {T.line}; border-bottom: 1px solid {T.line}; }}
    QFrame#result {{ background: {T.surface}; border: 1px solid {T.line}; border-radius: 12px; }}
    QPlainTextEdit {{ background: {T.surface}; border: 1px solid {T.line}; border-radius: 12px; padding: 17px; font-size: 16px; line-height: 1.5; selection-background-color: {T.red_dark}; }}
    QPlainTextEdit:focus {{ border: 1px solid {T.red}; }}
    QPushButton {{ background: transparent; color: {T.text}; border: 1px solid {T.line}; border-radius: 10px; padding: 10px 18px; font-weight: 700; }}
    QPushButton:hover {{ border-color: {T.red}; color: {T.red}; }}
    QPushButton#navAction {{ border: 0; color: {T.muted}; padding: 8px 10px; }}
    QPushButton#navAction:hover {{ color: {T.text}; }}
    QPushButton#primary {{ background: {T.red}; color: white; border: 0; border-radius: 10px; min-height: 44px; padding: 0 30px; font-family: "{display}"; font-size: 15px; }}
    QPushButton#primary:hover {{ background: {T.red_hover}; color: white; }}
    QPushButton#primary:disabled {{ background: #301313; color: #754545; }}
    QPushButton#textAction {{ border: 0; color: {T.muted}; padding: 6px; }}
    QPushButton#textAction:hover {{ color: {T.text}; }}
    QTabWidget::pane {{ background: transparent; border: 0; border-top: 1px solid {T.line}; }}
    QTabBar::tab {{ background: transparent; color: {T.muted}; border: 0; padding: 12px 20px 10px; font-size: 11px; font-weight: 800; letter-spacing: 1.2px; }}
    QTabBar::tab:selected {{ color: {T.text}; border-bottom: 2px solid {T.red}; }}
    QProgressBar {{ background: {T.elevated}; border: 0; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {T.red}; border-radius: 3px; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: #343434; border-radius: 3px; min-height: 28px; }}
    QToolTip {{ background: {T.elevated}; color: {T.text}; border: 1px solid {T.line}; padding: 6px; }}
    """


class WaveIcon(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(46, 46)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(T.red), 2))
        heights = (10, 22, 34, 18, 28, 12)
        for index, height in enumerate(heights):
            x = 7 + index * 6
            painter.drawLine(x, 23 - height // 2, x, 23 + height // 2)


def hairline() -> QFrame:
    frame = QFrame()
    frame.setObjectName("hairline")
    return frame


def label(text: str, object_name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    widget.setWordWrap(True)
    return widget


class PauseChoice(QFrame):
    def __init__(self, number: str, name: str, description: str, active: bool = False) -> None:
        super().__init__()
        self.setObjectName("pauseChoiceActive" if active else "pauseChoice")
        self.setMinimumHeight(78)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(13)
        row.addWidget(label(number, "numberActive" if active else "number"))
        copy = QVBoxLayout()
        copy.setSpacing(4)
        copy.addWidget(label(name.upper(), "kicker" if active else "status"))
        copy.addWidget(label(description, "muted"))
        copy.addStretch(1)
        row.addLayout(copy, 1)


class PrototypeWindow(QMainWindow):
    def __init__(self, state: str) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("LARP Audio — design exploration")
        self.resize(1440, 900)
        self.setMinimumSize(1440, 900)
        display, body = system_fonts()
        self.setStyleSheet(stylesheet(display, body))
        self.setCentralWidget(self._build())

    def _build(self) -> QWidget:
        root = QWidget()
        page = QVBoxLayout(root)
        page.setContentsMargins(38, 18, 38, 22)
        page.setSpacing(0)
        page.addLayout(self._header())
        page.addWidget(hairline())
        strip = label("AUDIO   /   SCRIPT   /   PROCESS   /   REVIEW", "strip")
        strip.setAlignment(Qt.AlignCenter)
        page.addWidget(strip)
        page.addLayout(self._inputs(), 3)
        page.addSpacing(11)
        page.addLayout(self._pause_styles())
        page.addSpacing(10)
        page.addWidget(self._setup_bar())
        page.addSpacing(10)
        page.addWidget(self._result_area(), 2)
        return root

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 13)
        row.setSpacing(14)
        brand = QVBoxLayout()
        brand.setSpacing(1)
        brand.addWidget(label("LARP AUDIO", "brand"))
        brand.addWidget(label("Voiceover and exact script into timed subtitles.", "statement"))
        row.addLayout(brand)
        row.addStretch(1)
        dot = label("●", "kicker")
        dot.setFixedWidth(14)
        row.addWidget(dot)
        row.addWidget(label("LOCAL PROCESSING", "status"))
        row.addSpacing(13)
        advanced = QPushButton("Advanced Settings")
        advanced.setObjectName("navAction")
        about = QPushButton("About")
        about.setObjectName("navAction")
        start_over = QPushButton("Start over")
        start_over.setObjectName("navAction")
        row.addWidget(start_over)
        row.addWidget(advanced)
        row.addWidget(about)
        return row

    def _inputs(self) -> QHBoxLayout:
        ready = self.state != "empty"
        row = QHBoxLayout()
        row.setSpacing(18)

        audio = QFrame()
        audio.setObjectName("inputSurface")
        audio.setFixedWidth(355)
        audio_layout = QVBoxLayout(audio)
        audio_layout.setContentsMargins(20, 17, 20, 17)
        audio_layout.setSpacing(10)
        audio_layout.addWidget(label("AUDIO", "kicker"))
        audio_layout.addWidget(label("Voiceover", "display"))
        drop = QFrame()
        drop.setObjectName("audioDrop")
        drop_layout = QVBoxLayout(drop)
        drop_layout.setContentsMargins(17, 12, 17, 12)
        drop_layout.setSpacing(5)
        top = QHBoxLayout()
        top.addWidget(WaveIcon())
        copy = QVBoxLayout()
        if ready:
            copy.addWidget(label("voiceover.wav", "section"))
            copy.addWidget(label("04:28 · WAV · 48 kHz · MONO", "tiny"))
        else:
            copy.addWidget(label("Choose a voiceover audio file", "section"))
            copy.addWidget(label("MP3, WAV, M4A · stays on this device", "tiny"))
        top.addLayout(copy, 1)
        drop_layout.addLayout(top)
        actions = QHBoxLayout()
        upload = QPushButton("Replace" if ready else "Upload audio")
        upload.setObjectName("primary" if not ready else "")
        actions.addWidget(upload)
        if ready:
            remove = QPushButton("Remove")
            remove.setObjectName("textAction")
            actions.addWidget(remove)
        actions.addStretch(1)
        drop_layout.addLayout(actions)
        audio_layout.addWidget(drop, 1)
        row.addWidget(audio)

        script = QFrame()
        script.setObjectName("inputSurface")
        script_layout = QVBoxLayout(script)
        script_layout.setContentsMargins(20, 17, 20, 14)
        script_layout.setSpacing(8)
        title_row = QHBoxLayout()
        script_kicker = label("ORIGINAL SCRIPT", "kicker")
        script_kicker.setWordWrap(False)
        title_row.addWidget(script_kicker)
        title_row.addStretch(1)
        script_layout.addLayout(title_row)
        script_layout.addWidget(label("Exact text", "display"))
        editor = QPlainTextEdit()
        editor.setPlaceholderText("Paste the exact voiceover script here")
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if ready:
            editor.setPlainText(
                "Most creators lose time between good takes.\n"
                "LARP Audio trims pauses without touching the words."
            )
        script_layout.addWidget(editor, 1)
        actions = QHBoxLayout()
        count = label("1,248 CHARACTERS · 218 WORDS" if ready else "0 CHARACTERS · 0 WORDS", "tiny")
        count.setWordWrap(False)
        actions.addWidget(count)
        actions.addStretch(1)
        actions.addWidget(QPushButton("Upload script"))
        clear = QPushButton("Clear")
        clear.setObjectName("textAction")
        actions.addWidget(clear)
        script_layout.addLayout(actions)
        row.addWidget(script, 1)
        return row

    def _pause_styles(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(0)
        row.addWidget(PauseChoice("01", "Tight", "Fastest pacing"), 1)
        row.addWidget(PauseChoice("02", "Balanced", "Natural short-form pacing", active=True), 1)
        row.addWidget(PauseChoice("03", "Natural", "More breathing room"), 1)
        return row

    def _setup_bar(self) -> QFrame:
        ready = self.state != "empty"
        bar = QFrame()
        bar.setObjectName("setupBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 14, 10)
        layout.setSpacing(24)
        model = QVBoxLayout()
        model.setSpacing(1)
        model.addWidget(label("SPEECH MODEL", "tiny"))
        model.addWidget(label("Tiny · CPU · Ready" if ready else "Choose local model", "status"))
        layout.addLayout(model, 1)
        save = QVBoxLayout()
        save.setSpacing(1)
        save.addWidget(label("SAVE LOCATION", "tiny"))
        save.addWidget(label("Voiceovers / July" if ready else "Choose result folder", "status"))
        layout.addLayout(save, 1)
        readiness = "●  READY" if ready else "NOT READY"
        layout.addWidget(label(readiness, "kicker" if ready else "tiny"))
        if self.state == "processing":
            cancel = QPushButton("Cancel")
            layout.addWidget(cancel)
            process = QPushButton("Processing…")
        else:
            process = QPushButton("Process")
        process.setObjectName("primary")
        process.setEnabled(ready and self.state != "processing")
        layout.addWidget(process)
        return bar

    def _result_area(self) -> QWidget:
        result = QFrame()
        result.setObjectName("result")
        layout = QVBoxLayout(result)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(8)
        if self.state in {"empty", "ready"}:
            row = QHBoxLayout()
            copy = QVBoxLayout()
            copy.addWidget(label("RESULT", "kicker"))
            copy.addWidget(label("Nothing processed yet", "section"))
            copy.addWidget(label("Cleaned audio, subtitle blocks and files will appear here.", "muted"))
            row.addLayout(copy, 1)
            layout.addLayout(row)
            return result
        if self.state == "processing":
            top = QHBoxLayout()
            copy = QVBoxLayout()
            copy.addWidget(label("PROCESSING AUDIO", "section"))
            copy.addWidget(label("Recognizing speech · step 3 of 7", "kicker"))
            top.addLayout(copy, 1)
            script_safety = label("Your script stays unchanged", "tiny")
            script_safety.setWordWrap(False)
            top.addWidget(script_safety)
            layout.addLayout(top)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(46)
            layout.addWidget(progress)
            events = QHBoxLayout()
            events.addWidget(label("✓  AUDIO PREPARED", "tiny"))
            events.addSpacing(28)
            events.addWidget(label("✓  PAUSES SHORTENED", "tiny"))
            events.addSpacing(28)
            events.addWidget(label("●  RECOGNIZING", "kicker"))
            events.addStretch(1)
            layout.addLayout(events)
            return result

        tabs = QTabWidget()
        for name in ("PREVIEW", "SUBTITLE BLOCKS", "DIAGNOSTICS", "FILES"):
            tab = QWidget()
            tabs.addTab(tab, name)
        preview = tabs.widget(0)
        preview_layout = QHBoxLayout(preview)
        preview_layout.setContentsMargins(0, 12, 0, 0)
        cue_list = QVBoxLayout()
        cue_list.addWidget(label("CLEANED TIMELINE", "kicker"))
        for index, cue in (("01", "Most creators lose time"), ("02", "in the gaps between good takes."), ("03", "LARP Audio finds the pauses")):
            cue_row = QHBoxLayout()
            cue_row.addWidget(label(index, "cueNumberActive" if index == "02" else "cueNumber"))
            cue_row.addWidget(label(cue, "section" if index == "02" else "muted"), 1)
            cue_list.addLayout(cue_row)
        preview_layout.addLayout(cue_list, 2)
        preview_layout.addWidget(hairline())
        current = QVBoxLayout()
        current.addWidget(label("NOW PLAYING · 02", "kicker"))
        current.addWidget(label("in the gaps between\ngood takes.", "display"), 1)
        current.addWidget(label("00:03.420 — 00:05.180   /   16.8 CPS   /   OBSERVED", "tiny"))
        transport = QHBoxLayout()
        for text in ("Previous", "Play", "Stop", "Next", "Reload"):
            transport.addWidget(QPushButton(text))
        current.addLayout(transport)
        preview_layout.addLayout(current, 3)
        layout.addWidget(tabs, 1)
        return result


def save_screenshot(app: QApplication, state: str, path: Path) -> None:
    window = PrototypeWindow(state)
    window.show()
    app.processEvents()
    image = window.grab().toImage()
    if image.size().width() != 1440 or image.size().height() != 900:
        raise RuntimeError(f"Unexpected prototype size: {image.size().width()}x{image.size().height()}")
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save {path}")
    window.close()
    app.processEvents()


def draw_fitted(painter: QPainter, image: QImage, rect: QRect) -> None:
    scaled = image.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    x = rect.x() + (rect.width() - scaled.width()) // 2
    y = rect.y() + (rect.height() - scaled.height()) // 2
    painter.drawImage(x, y, scaled)


def create_comparison_board(prototype_path: Path, output: Path) -> None:
    board = QImage(1800, 1200, QImage.Format_RGB32)
    board.fill(QColor(T.canvas))
    painter = QPainter(board)
    painter.setRenderHint(QPainter.Antialiasing)
    display, body = system_fonts()
    painter.setPen(QColor(T.text))
    painter.setFont(QFont(display, 30, QFont.Black))
    painter.drawText(QRect(54, 34, 1692, 52), Qt.AlignLeft | Qt.AlignVCenter, "REFERENCE DNA → DESKTOP WORKFLOW")
    painter.setPen(QColor(T.muted))
    painter.setFont(QFont(body, 13, QFont.Medium))
    painter.drawText(QRect(56, 82, 1690, 30), Qt.AlignLeft | Qt.AlignVCenter, "Unmodified reference captures compared with the isolated LARP Audio PySide6 prototype")
    cells = (
        (REFERENCE_SCREENSHOTS[0], "01 / NUMBERED PROCESS", "Number + title + concise supporting copy"),
        (REFERENCE_SCREENSHOTS[1], "02 / EDITORIAL HIERARCHY", "Oversized statement, compact red kicker, open space"),
        (REFERENCE_SCREENSHOTS[2], "03 / METRIC EMPHASIS", "Large values, restrained panels, one focused red state"),
        (prototype_path, "04 / LARP AUDIO PROTOTYPE", "Numbered workflow, dominant script, integrated review"),
    )
    positions = (QRect(54, 138, 822, 445), QRect(924, 138, 822, 445), QRect(54, 647, 822, 445), QRect(924, 647, 822, 445))
    for (path, title, subtitle), outer in zip(cells, positions, strict=True):
        painter.setPen(QPen(QColor(T.line), 1))
        painter.setBrush(QColor(T.surface))
        painter.drawRoundedRect(outer, 14, 14)
        image_rect = QRect(outer.x() + 12, outer.y() + 12, outer.width() - 24, outer.height() - 82)
        source = QImage(str(path))
        if source.isNull():
            raise RuntimeError(f"Cannot read comparison source {path}")
        draw_fitted(painter, source, image_rect)
        painter.setPen(QColor(T.red))
        painter.setFont(QFont(display, 13, QFont.Black))
        painter.drawText(QRect(outer.x() + 18, outer.bottom() - 61, outer.width() - 36, 24), Qt.AlignLeft | Qt.AlignVCenter, title)
        painter.setPen(QColor(T.muted))
        painter.setFont(QFont(body, 11, QFont.Normal))
        painter.drawText(QRect(outer.x() + 18, outer.bottom() - 37, outer.width() - 36, 22), Qt.AlignLeft | Qt.AlignVCenter, subtitle)
    painter.end()
    if not board.save(str(output), "PNG"):
        raise RuntimeError(f"Could not save {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the isolated AdsCreativeHouse-inspired PySide6 prototype")
    parser.add_argument("--render", action="store_true", help="render all approval screenshots")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(["larp-design-prototype"])
    if args.render:
        ROOT.mkdir(parents=True, exist_ok=True)
        for state in ("empty", "ready", "processing", "result"):
            save_screenshot(app, state, ROOT / f"adscreativehouse_{state}.png")
        create_comparison_board(ROOT / "adscreativehouse_result.png", ROOT / "reference_comparison.png")
        return 0
    window = PrototypeWindow("ready")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
