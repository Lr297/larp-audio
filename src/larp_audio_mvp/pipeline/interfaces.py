"""Minimal pipeline ports.

These Protocols describe dependency direction only. Concrete adapters live in
their stage packages and depend on these ports rather than redefining them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from larp_audio_mvp.config import ModelSettings, PauseSettings, SubtitleSettings
from larp_audio_mvp.core.contracts import (
    AlignmentResult,
    ArtifactRecord,
    AudioInfo,
    AudioLoadResult,
    EditMap,
    InputProject,
    PauseSegment,
    PauseRemovalResult,
    ProcessingReport,
    RecognitionResult,
    ScriptDocument,
    SubtitleBlock,
    SubtitleDocument,
)


@runtime_checkable
class AudioLoader(Protocol):
    """Probe a local source and prepare a canonical working copy."""

    def load(self, source: Path) -> AudioLoadResult: ...


@runtime_checkable
class PauseDetector(Protocol):
    """Find possible pauses without modifying audio."""

    def detect(
        self,
        audio: AudioInfo,
        *,
        settings: PauseSettings,
    ) -> Sequence[PauseSegment]: ...


@runtime_checkable
class PauseRemover(Protocol):
    """Create cleaned audio and its edit map from approved candidates."""

    def remove(
        self,
        audio: AudioInfo,
        candidates: Sequence[PauseSegment],
        *,
        destination: Path,
    ) -> PauseRemovalResult: ...


@runtime_checkable
class SpeechRecognizer(Protocol):
    """Return local timing observations; text is never a display source."""

    def recognize(
        self,
        audio: AudioInfo,
        edit_map: EditMap,
        *,
        settings: ModelSettings,
    ) -> RecognitionResult: ...


@runtime_checkable
class WordAligner(Protocol):
    """Associate immutable script spans with timing observations."""

    def align(
        self,
        script: ScriptDocument,
        recognition: RecognitionResult,
        edit_map: EditMap,
    ) -> AlignmentResult: ...


@runtime_checkable
class SubtitleChunker(Protocol):
    """Build canonical blocks from already aligned original-script spans."""

    def chunk(
        self,
        alignment: AlignmentResult,
        *,
        settings: SubtitleSettings,
        source_alignment_sha256: str,
    ) -> SubtitleDocument: ...


@runtime_checkable
class Exporter(Protocol):
    """Serialize one export profile from validated canonical contracts."""

    @property
    def format_name(self) -> str: ...

    def export(
        self,
        project: InputProject,
        audio: AudioInfo,
        edit_map: EditMap,
        subtitles: Sequence[SubtitleBlock],
        report: ProcessingReport,
        *,
        destination: Path,
    ) -> Sequence[ArtifactRecord]: ...
