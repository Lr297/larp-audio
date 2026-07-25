"""Headless orchestration for audio probe and canonicalization."""

from __future__ import annotations

from pathlib import Path

from larp_audio_mvp.audio.converter import CanonicalWavConverter
from larp_audio_mvp.audio.probe import FfprobeAdapter
from larp_audio_mvp.core.contracts import AudioInfo, AudioLoadResult
from larp_audio_mvp.core.logging import get_logger


class LocalAudioLoader:
    """Implement the AudioLoader port without exposing subprocess details."""

    def __init__(
        self,
        *,
        probe: FfprobeAdapter,
        converter: CanonicalWavConverter,
        work_directory: Path,
        canonical_filename: str = "canonical_audio.wav",
    ) -> None:
        if Path(canonical_filename).name != canonical_filename:
            raise ValueError("canonical_filename must not contain directories")
        self._probe = probe
        self._converter = converter
        self._work_directory = work_directory.expanduser().resolve()
        self._canonical_filename = canonical_filename
        self._logger = get_logger("audio.loader")

    def load(self, source: Path) -> AudioLoadResult:
        self._logger.info("starting audio ingestion")
        source_audio = self.analyze(source)
        canonical_audio = self.canonicalize(source_audio)
        self._logger.info("audio ingestion completed")
        return AudioLoadResult(
            source_audio=source_audio,
            canonical_audio=canonical_audio,
        )

    def analyze(self, source: Path) -> AudioInfo:
        """Probe source metadata without performing canonical conversion."""
        return self._probe.probe(source)

    def canonicalize(self, source_audio: AudioInfo) -> AudioInfo:
        """Run the actual canonical conversion as its own pipeline stage."""
        return self._converter.convert(
            source_audio,
            self._work_directory / self._canonical_filename,
        )
