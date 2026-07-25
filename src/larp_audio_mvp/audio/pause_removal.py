"""Headless orchestration for policy, edit-map construction, and rendering."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.audio.edit_map_builder import EditMapBuilder
from larp_audio_mvp.audio.pause_policy import PauseShorteningPolicy
from larp_audio_mvp.audio.pause_renderer import FfmpegWavRenderer
from larp_audio_mvp.core.contracts import (
    AudioInfo,
    EditMap,
    PauseRemovalResult,
    PauseSegment,
)
from larp_audio_mvp.core.errors import EditMapError


class PauseRemovalService:
    """Implement the PauseRemover port without embedding subprocess details."""

    def __init__(
        self,
        *,
        policy: PauseShorteningPolicy,
        builder: EditMapBuilder,
        renderer: FfmpegWavRenderer,
    ) -> None:
        self._policy = policy
        self._builder = builder
        self._renderer = renderer

    def remove(
        self,
        audio: AudioInfo,
        candidates: Sequence[PauseSegment],
        *,
        destination: Path,
    ) -> PauseRemovalResult:
        edit_map = self.plan(audio, candidates)
        return self.render(audio, edit_map, destination=destination)

    def plan(
        self,
        audio: AudioInfo,
        candidates: Sequence[PauseSegment],
    ) -> EditMap:
        """Apply policy and build an edit map without rendering audio."""
        if audio.total_samples is None:
            raise EditMapError(
                "pause removal requires exact total_samples",
                code="MISSING_TOTAL_SAMPLES",
            )
        decisions = self._policy.decide(
            candidates,
            total_samples=audio.total_samples,
            sample_rate=audio.sample_rate,
        )
        return self._builder.build(
            audio,
            decisions,
            policy=self._policy,
        )

    def render(self, audio: AudioInfo, edit_map: EditMap, *, destination: Path) -> PauseRemovalResult:
        """Render a previously planned edit map as a distinct heavy stage."""
        cleaned_audio = self._renderer.render(audio, edit_map, destination)
        completed_map = replace(edit_map, output_sha256=cleaned_audio.sha256)
        return PauseRemovalResult(
            cleaned_audio_path=cleaned_audio.source_path,
            edit_map=completed_map,
            cleaned_audio=cleaned_audio,
        )
