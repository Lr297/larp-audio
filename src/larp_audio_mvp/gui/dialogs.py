"""Replaceable native file-dialog boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QFileDialog, QWidget


class DialogService(Protocol):
    def choose_audio(self, parent: QWidget) -> Path | None: ...

    def choose_script(self, parent: QWidget) -> Path | None: ...

    def choose_model_directory(self, parent: QWidget, initial: Path | None) -> Path | None: ...

    def choose_alignment(self, parent: QWidget) -> Path | None: ...

    def choose_output_directory(
        self, parent: QWidget, initial: Path | None
    ) -> Path | None: ...


class QtDialogService:
    def choose_audio(self, parent: QWidget) -> Path | None:
        selected, _ = QFileDialog.getOpenFileName(parent, "Upload audio", "", "Audio and media (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.mp4);;All files (*)")
        return Path(selected) if selected else None

    def choose_script(self, parent: QWidget) -> Path | None:
        selected, _ = QFileDialog.getOpenFileName(parent, "Upload script", "", "Text files (*.txt);;All files (*)")
        return Path(selected) if selected else None

    def choose_model_directory(self, parent: QWidget, initial: Path | None) -> Path | None:
        selected = QFileDialog.getExistingDirectory(parent, "Choose speech model", str(initial) if initial else "")
        return Path(selected) if selected else None

    def choose_alignment(self, parent: QWidget) -> Path | None:
        selected, _ = QFileDialog.getOpenFileName(
            parent,
            "Select alignment.json",
            "",
            "Alignment JSON (*.json);;All files (*)",
        )
        return Path(selected) if selected else None

    def choose_output_directory(
        self, parent: QWidget, initial: Path | None
    ) -> Path | None:
        selected = QFileDialog.getExistingDirectory(
            parent,
            "Choose where to save the result",
            str(initial) if initial is not None else "",
        )
        return Path(selected) if selected else None
