"""Immutable contracts for the two-file universal consumer export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.core.contracts import SubtitleDocument


@dataclass(frozen=True, slots=True)
class UniversalExportRequest:
    destination_folder: Path
    base_name: str
    cleaned_audio_source: Path
    cleaned_total_samples: int
    audio_sample_rate: int
    audio_channel_count: int
    subtitle_document: SubtitleDocument


@dataclass(frozen=True, slots=True)
class UniversalExportResult:
    export_name: str
    destination_folder: Path
    audio_path: Path
    subtitle_path: Path
    audio_sha256: str
    subtitle_sha256: str

    @property
    def published_files(self) -> tuple[Path, Path]:
        return (self.audio_path, self.subtitle_path)
