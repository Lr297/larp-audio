#!/usr/bin/env python3
"""Render the original LARP waveform mark into complete Apple icon resources."""

from pathlib import Path
import subprocess

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QRadialGradient

ROOT = Path(__file__).resolve().parents[1]
MASTER_SIZE = 1024
MASTER_PATH = ROOT / "resources/icons/larp_audio_master.png"
ICONSET_PATH = ROOT / "resources/icons/larp_audio.iconset"
ICNS_PATH = ROOT / "resources/icons/larp_audio.icns"


def draw_master(path: Path) -> None:
    image = QImage(MASTER_SIZE, MASTER_SIZE, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    icon_rect = QRectF(56, 56, 912, 912)
    silhouette = QPainterPath()
    silhouette.addRoundedRect(icon_rect, 208, 208)
    background = QRadialGradient(512, 430, 690)
    background.setColorAt(0.0, QColor("#171719"))
    background.setColorAt(0.70, QColor("#0b0b0c"))
    background.setColorAt(1.0, QColor("#050506"))
    painter.fillPath(silhouette, background)

    painter.setClipPath(silhouette)
    accent = QPen(QColor("#ff3f3d"), 54, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(accent)
    segments = (
        (214, 512, 286, 512),
        (340, 374, 340, 650),
        (426, 284, 426, 740),
        (512, 422, 512, 602),
        (598, 352, 598, 672),
        (684, 512, 810, 512),
    )
    for x1, y1, x2, y2 in segments:
        painter.drawLine(x1, y1, x2, y2)
    painter.end()
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not write icon master: {path}")


def render_size(master: QImage, size: int, path: Path) -> None:
    scaled = master.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if not scaled.save(str(path), "PNG"):
        raise RuntimeError(f"Could not write icon size: {path}")


def main() -> None:
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICONSET_PATH.mkdir(parents=True, exist_ok=True)
    draw_master(MASTER_PATH)
    master = QImage(str(MASTER_PATH))
    if master.isNull() or master.size().width() != MASTER_SIZE or master.size().height() != MASTER_SIZE:
        raise RuntimeError("Generated icon master is not a valid 1024x1024 image")
    for points in (16, 32, 128, 256, 512):
        render_size(master, points, ICONSET_PATH / f"icon_{points}x{points}.png")
        render_size(master, points * 2, ICONSET_PATH / f"icon_{points}x{points}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET_PATH), "-o", str(ICNS_PATH)], check=True)
    print(MASTER_PATH)
    print(ICNS_PATH)


if __name__ == "__main__":
    main()
