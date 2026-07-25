"""Testable media boundary; production Qt Multimedia is imported elsewhere."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from .contracts import PlaybackState


class EventHook:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def disconnect(self, callback: Callable[..., None] | None = None) -> None:
        if callback is None:
            self._callbacks.clear()
        elif callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, *args: object) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class MediaBackend(Protocol):
    media_loaded: EventHook
    position_changed: EventHook
    duration_changed: EventHook
    playback_state_changed: EventHook
    media_status_changed: EventHook
    error_occurred: EventHook

    def load(self, path: Path) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def seek(self, milliseconds: int) -> None: ...
    def set_volume(self, value: int) -> None: ...
    def set_muted(self, muted: bool) -> None: ...
    def current_position(self) -> int: ...
    def duration(self) -> int: ...
    def playback_state(self) -> PlaybackState: ...
    def dispose(self) -> None: ...
