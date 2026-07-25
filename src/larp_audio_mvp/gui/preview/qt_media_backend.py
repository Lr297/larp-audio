"""QMediaPlayer adapter with delayed, controlled QtMultimedia imports."""

from __future__ import annotations

from pathlib import Path

from larp_audio_mvp.core.errors import PreviewError

from .contracts import PlaybackState
from .media_backend import EventHook


class QtMediaBackend:
    def __init__(self, parent: object | None = None) -> None:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except (ImportError, OSError) as exc:
            raise PreviewError(
                "Qt Multimedia is unavailable in this installation.",
                code="PREVIEW_MULTIMEDIA_UNAVAILABLE",
            ) from exc
        self._QUrl = QUrl
        self._QMediaPlayer = QMediaPlayer
        self._player = QMediaPlayer(parent)
        self._audio = QAudioOutput(parent)
        self._player.setAudioOutput(self._audio)
        self.media_loaded = EventHook(); self.position_changed = EventHook(); self.duration_changed = EventHook()
        self.playback_state_changed = EventHook(); self.media_status_changed = EventHook(); self.error_occurred = EventHook()
        self._player.positionChanged.connect(self.position_changed.emit)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.playbackStateChanged.connect(lambda _value: self.playback_state_changed.emit(self.playback_state()))
        self._player.mediaStatusChanged.connect(self._status)
        self._player.errorOccurred.connect(lambda _error, message: self.error_occurred.emit("PREVIEW_MEDIA_ERROR", message or "Media playback failed."))

    def _status(self, status: object) -> None:
        self.media_status_changed.emit(str(status))
        if status == self._QMediaPlayer.MediaStatus.LoadedMedia:
            self.media_loaded.emit()

    def load(self, path: Path) -> None:
        if not path.is_file():
            raise PreviewError("Cleaned audio no longer exists.", code="PREVIEW_AUDIO_MISSING")
        self._player.setSource(self._QUrl.fromLocalFile(str(path)))

    def play(self) -> None: self._player.play()
    def pause(self) -> None: self._player.pause()
    def stop(self) -> None: self._player.stop()
    def seek(self, milliseconds: int) -> None: self._player.setPosition(max(0, min(milliseconds, self.duration())))
    def set_volume(self, value: int) -> None: self._audio.setVolume(max(0, min(value, 100)) / 100)
    def set_muted(self, muted: bool) -> None: self._audio.setMuted(bool(muted))
    def current_position(self) -> int: return int(self._player.position())
    def duration(self) -> int: return int(self._player.duration())
    def playback_state(self) -> PlaybackState:
        value = self._player.playbackState()
        if value == self._QMediaPlayer.PlaybackState.PlayingState: return PlaybackState.PLAYING
        if value == self._QMediaPlayer.PlaybackState.PausedState: return PlaybackState.PAUSED
        return PlaybackState.STOPPED

    def dispose(self) -> None:
        self.stop()
        self._player.setSource(self._QUrl())
        for event in (self.media_loaded, self.position_changed, self.duration_changed, self.playback_state_changed, self.media_status_changed, self.error_occurred):
            event.disconnect()
