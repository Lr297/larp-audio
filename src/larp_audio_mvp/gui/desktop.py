"""Desktop actions isolated from widgets and platform-specific shell commands."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QClipboard, QDesktopServices

from larp_audio_mvp.core.errors import DesktopActionError


class DesktopService:
    def open_path(self, path: Path) -> None:
        resolved = path.expanduser().resolve(strict=False)
        if not resolved.exists():
            raise DesktopActionError(
                f"Path does not exist: {resolved}", code="DESKTOP_PATH_MISSING"
            )
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
            raise DesktopActionError(
                f"The operating system could not open: {resolved}",
                code="DESKTOP_OPEN_FAILED",
            )

    @staticmethod
    def copy_path(path: Path, clipboard: QClipboard) -> None:
        clipboard.setText(str(path.expanduser().resolve(strict=False)))
