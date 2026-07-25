"""Immutable contracts for read-only cleaned-timeline preview."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from larp_audio_mvp.core.contracts import SubtitleDocument


class PreviewPhase(StrEnum):
    UNAVAILABLE = "preview_unavailable"
    PREPARING = "preview_preparing"
    READY = "preview_ready"
    PLAYING = "preview_playing"
    PAUSED = "preview_paused"
    ERROR = "preview_error"


class PlaybackState(StrEnum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DiagnosticEntry:
    section: str
    label: str
    value: str
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO


@dataclass(frozen=True, slots=True)
class PreviewDiagnostics:
    run_id: str
    entries: tuple[DiagnosticEntry, ...]
    package_valid: bool
    provenance_valid: bool
    media_backend: str = "pending"


@dataclass(frozen=True, slots=True)
class PreviewSource:
    cleaned_audio_path: Path
    subtitle_document: SubtitleDocument
    sample_rate: int
    cleaned_total_samples: int
    audio_sha256: str
    subtitle_document_sha256: str
    run_id: str
    source_origin: str
    diagnostics: PreviewDiagnostics


@dataclass(frozen=True, slots=True)
class ActiveSubtitleCue:
    block_index: int
    cleaned_start_sample: int
    cleaned_end_sample: int
    display_lines: tuple[str, ...]
    timing_provenance: str
    characters_per_second: str
    word_count: int
    warnings: tuple[str, ...]
    contains_interpolated_words: bool
    contains_unresolved_words: bool
    display_start_sample: int
    display_end_sample: int


@dataclass(frozen=True, slots=True)
class PreviewFailure:
    code: str
    message: str
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class PreviewState:
    session_id: str | None = None
    phase: PreviewPhase = PreviewPhase.UNAVAILABLE
    source_loaded: bool = False
    playback_state: PlaybackState = PlaybackState.STOPPED
    position_milliseconds: int = 0
    duration_milliseconds: int = 0
    active_block_index: int | None = None
    selected_block_index: int | None = None
    volume: int = 80
    muted: bool = False
    follow_playback: bool = True
    auto_scroll: bool = True
    failure: PreviewFailure | None = None
    diagnostics: PreviewDiagnostics | None = None
    media_available: bool = False
    active_cue_hidden_by_filter: bool = False
    source: PreviewSource | None = field(default=None, repr=False)
