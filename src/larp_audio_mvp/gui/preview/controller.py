"""Fast playback/cue state machine independent of concrete widgets."""

from __future__ import annotations

import uuid
from dataclasses import replace

from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import get_logger

from .contracts import PlaybackState, PreviewFailure, PreviewPhase, PreviewSource, PreviewState
from .media_backend import EventHook, MediaBackend
from .synchronization import SubtitleSynchronizer

LOGGER = get_logger("gui.preview")


class PreviewController:
    def __init__(self, backend: MediaBackend) -> None:
        self.backend = backend
        self.state = PreviewState()
        self.state_changed = EventHook()
        self._sync: SubtitleSynchronizer | None = None
        self.backend.set_volume(self.state.volume)

    def _connect_backend(self, session: str) -> None:
        for event in (self.backend.media_loaded, self.backend.position_changed, self.backend.duration_changed, self.backend.playback_state_changed, self.backend.error_occurred):
            event.disconnect()
        self.backend.media_loaded.connect(lambda: self._on_loaded(session))
        self.backend.position_changed.connect(lambda value: self._on_position(session, value))
        self.backend.duration_changed.connect(lambda value: self._on_duration(session, value))
        self.backend.playback_state_changed.connect(lambda value: self._on_playback(session, value))
        self.backend.error_occurred.connect(lambda code, message: self._on_error(session, code, message))

    def _publish(self, state: PreviewState) -> None:
        self.state = state; self.state_changed.emit(state)

    def load(self, source: PreviewSource) -> str:
        self.reset()
        session = uuid.uuid4().hex
        self._connect_backend(session)
        self._sync = SubtitleSynchronizer(source.subtitle_document)
        duration = source.cleaned_total_samples * 1000 // source.sample_rate
        self._publish(PreviewState(session_id=session, phase=PreviewPhase.PREPARING, duration_milliseconds=duration, source=source, diagnostics=source.diagnostics, volume=self.state.volume))
        try:
            self.backend.load(source.cleaned_audio_path)
        except ProjectError as exc:
            self._on_error(session, exc.code, str(exc))
        return session

    def _on_loaded(self, session: str) -> None:
        if self.state.session_id == session:
            self._publish(replace(self.state, source_loaded=True, media_available=True, phase=PreviewPhase.READY, failure=None))

    def _on_position(self, session: str, milliseconds: object) -> None:
        if self.state.session_id != session or not isinstance(milliseconds, int): return
        value = max(0, min(milliseconds, self.state.duration_milliseconds))
        cue = self._sync.cue_at_milliseconds(value) if self._sync else None
        self._publish(replace(self.state, position_milliseconds=value, active_block_index=None if cue is None else cue.block_index))

    def _on_duration(self, session: str, milliseconds: object) -> None:
        if self.state.session_id == session and isinstance(milliseconds, int) and milliseconds >= 0:
            self._publish(replace(self.state, duration_milliseconds=milliseconds))

    def _on_playback(self, session: str, playback: object) -> None:
        if self.state.session_id != session or not isinstance(playback, PlaybackState): return
        phase = {PlaybackState.PLAYING: PreviewPhase.PLAYING, PlaybackState.PAUSED: PreviewPhase.PAUSED, PlaybackState.STOPPED: PreviewPhase.READY}[playback]
        self._publish(replace(self.state, playback_state=playback, phase=phase))

    def _on_error(self, session: str, code: object, message: object) -> None:
        if self.state.session_id != session: return
        failure = PreviewFailure(str(code), str(message))
        self._publish(replace(self.state, phase=PreviewPhase.ERROR, media_available=False, failure=failure))

    def play_pause(self) -> None:
        if not self.state.media_available: return
        self.backend.pause() if self.state.playback_state is PlaybackState.PLAYING else self.backend.play()

    def stop(self) -> None:
        self.backend.stop(); self.backend.seek(0)

    def seek(self, milliseconds: int) -> None:
        if self.state.media_available: self.backend.seek(max(0, min(milliseconds, self.state.duration_milliseconds)))

    def select(self, block_index: int | None) -> None: self._publish(replace(self.state, selected_block_index=block_index))
    def seek_to_block(self, block_index: int) -> None:
        if self._sync: self.seek(self._sync.milliseconds_for_block(block_index))
    def next_cue(self) -> None:
        if self._sync and self._sync.document.blocks:
            current = self.state.active_block_index or self.state.selected_block_index or 0
            self.seek_to_block(min(len(self._sync.document.blocks), current + 1))
    def previous_cue(self) -> None:
        if self._sync and self._sync.document.blocks:
            current = self.state.active_block_index or self.state.selected_block_index or 1
            block = self._sync.document.blocks[current - 1]
            current_start = block.cleaned_start_sample * 1000 // self._sync.document.sample_rate
            target = current if self.state.position_milliseconds - current_start > 750 else max(1, current - 1)
            self.seek_to_block(target)
    def set_volume(self, value: int) -> None:
        value = max(0, min(value, 100)); self.backend.set_volume(value); self._publish(replace(self.state, volume=value))
    def set_muted(self, muted: bool) -> None:
        self.backend.set_muted(muted); self._publish(replace(self.state, muted=muted))
    def set_follow_playback(self, enabled: bool) -> None: self._publish(replace(self.state, follow_playback=enabled))
    def set_auto_scroll(self, enabled: bool) -> None: self._publish(replace(self.state, auto_scroll=enabled))
    def reset(self) -> None:
        if self.state.session_id:
            self.backend.stop()
        volume = self.state.volume
        self._sync = None; self._publish(PreviewState(volume=volume))
    def dispose(self) -> None:
        self.reset(); self.backend.dispose()
