"""Cooperative cancellation shared by CLI, GUI worker, and pipeline service."""

from __future__ import annotations

from threading import Event

from larp_audio_mvp.core.errors import PipelineCancellationError


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()
        self._publication_started = Event()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    @property
    def cancellation_allowed(self) -> bool:
        return not self._publication_started.is_set()

    def request(self) -> bool:
        if not self.cancellation_allowed:
            return False
        self._event.set()
        return True

    def prevent_cancellation(self) -> None:
        self._publication_started.set()

    def check(self) -> None:
        if self.requested:
            raise PipelineCancellationError(
                "Processing was cancelled before publication.",
                code="PIPELINE_CANCELLED",
            )
