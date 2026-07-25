from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest

from larp_audio_mvp.gui.preview import EventHook, PreviewController, PreviewPreparationService, SubtitleSynchronizer
from larp_audio_mvp.gui.preview.contracts import PlaybackState, PreviewPhase
from larp_audio_mvp.core.errors import PreviewError
from tests.pipeline.test_full_pipeline import make_request, make_service


def _wait(qapp, predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate(): return
    raise AssertionError("preview GUI condition timed out")


class FakeMediaBackend:
    def __init__(self, *, auto_load: bool = True) -> None:
        self.media_loaded = EventHook(); self.position_changed = EventHook(); self.duration_changed = EventHook(); self.playback_state_changed = EventHook(); self.media_status_changed = EventHook(); self.error_occurred = EventHook()
        self.auto_load = auto_load; self.loaded: Path | None = None; self.position = 0; self.length = 10_000; self.state = PlaybackState.STOPPED; self.volume = 80; self.muted = False; self.disposed = False
    def load(self, path: Path) -> None:
        self.loaded = path
        if self.auto_load: self.media_loaded.emit(); self.duration_changed.emit(self.length)
    def play(self) -> None: self.state = PlaybackState.PLAYING; self.playback_state_changed.emit(self.state)
    def pause(self) -> None: self.state = PlaybackState.PAUSED; self.playback_state_changed.emit(self.state)
    def stop(self) -> None: self.state = PlaybackState.STOPPED; self.playback_state_changed.emit(self.state)
    def seek(self, milliseconds: int) -> None: self.position = milliseconds; self.position_changed.emit(milliseconds)
    def set_volume(self, value: int) -> None: self.volume = value
    def set_muted(self, muted: bool) -> None: self.muted = muted
    def current_position(self) -> int: return self.position
    def duration(self) -> int: return self.length
    def playback_state(self) -> PlaybackState: return self.state
    def dispose(self) -> None: self.disposed = True


@pytest.fixture
def preview_source(tmp_path: Path):
    result = make_service([]).run(make_request(tmp_path))
    return PreviewPreparationService().prepare(result)


def test_preview_preparation_strictly_validates_pipeline_result(preview_source) -> None:
    assert preview_source.audio_sha256
    assert preview_source.subtitle_document_sha256
    assert preview_source.diagnostics.package_valid
    assert preview_source.diagnostics.provenance_valid


@pytest.mark.parametrize("location", ("before", "start", "middle", "end", "gap", "after"))
def test_synchronizer_uses_half_open_cleaned_sample_intervals(preview_source, location: str) -> None:
    sync = SubtitleSynchronizer(preview_source.subtitle_document); first = preview_source.subtitle_document.blocks[0]
    values = {"before": max(0, first.cleaned_start_sample - 1), "start": first.cleaned_start_sample, "middle": (first.cleaned_start_sample + first.cleaned_end_sample) // 2, "end": first.cleaned_end_sample, "gap": first.cleaned_end_sample, "after": preview_source.cleaned_total_samples}
    block = sync.block_at_sample(values[location])
    if location in {"start", "middle", "end", "gap"}: assert block == first
    elif location == "end" and len(preview_source.subtitle_document.blocks) > 1 and preview_source.subtitle_document.blocks[1].cleaned_start_sample == first.cleaned_end_sample: assert block == preview_source.subtitle_document.blocks[1]
    else: assert block is None


def test_preview_controller_transport_navigation_and_error(preview_source) -> None:
    backend = FakeMediaBackend(); controller = PreviewController(backend); controller.load(preview_source)
    assert controller.state.phase is PreviewPhase.READY and controller.state.media_available
    controller.play_pause(); assert controller.state.playback_state is PlaybackState.PLAYING
    controller.play_pause(); assert controller.state.playback_state is PlaybackState.PAUSED
    controller.seek_to_block(1); assert backend.position == preview_source.subtitle_document.blocks[0].cleaned_start_sample * 1000 // preview_source.sample_rate
    backend.position_changed.emit(backend.position); assert controller.state.active_block_index == 1
    controller.next_cue(); controller.previous_cue(); controller.set_volume(31); controller.set_muted(True)
    assert backend.volume == 31 and backend.muted
    backend.error_occurred.emit("PREVIEW_MEDIA_ERROR", "broken")
    assert controller.state.phase is PreviewPhase.ERROR and controller.state.failure is not None
    controller.dispose(); assert backend.disposed


def test_stale_session_callbacks_are_ignored(preview_source) -> None:
    backend = FakeMediaBackend(auto_load=False); controller = PreviewController(backend)
    first = controller.load(preview_source); old_position = tuple(backend.position_changed._callbacks)[0]
    second_source = replace(preview_source, run_id="second")
    second = controller.load(second_source); assert first != second
    backend.media_loaded.emit(); old_position(9999)
    assert controller.state.session_id == second
    assert controller.state.position_milliseconds == 0


def test_stop_returns_to_zero(preview_source) -> None:
    backend = FakeMediaBackend(); controller = PreviewController(backend); controller.load(preview_source)
    controller.seek(500); controller.stop()
    assert backend.position == 0 and controller.state.position_milliseconds == 0


def test_internal_gap_holds_previous_until_exact_next_start(preview_source) -> None:
    document = preview_source.subtitle_document
    assert len(document.blocks) >= 2
    first, second, *rest = document.blocks
    speech_end = max(first.cleaned_start_sample + 1, second.cleaned_start_sample - 5_000)
    first = replace(first, cleaned_end_sample=speech_end, duration_samples=speech_end - first.cleaned_start_sample)
    gapped = replace(document, blocks=(first, second, *rest))
    sync = SubtitleSynchronizer(gapped)
    assert sync.block_at_sample(first.cleaned_end_sample) == first
    assert sync.block_at_sample(second.cleaned_start_sample - 1) == first
    assert sync.block_at_sample(second.cleaned_start_sample) == second
    cue = sync.cue_at_milliseconds((second.cleaned_start_sample - 1) * 1000 // document.sample_rate)
    assert cue is not None and cue.block_index == first.block_index
    assert cue.cleaned_end_sample == speech_end
    assert cue.display_end_sample == second.cleaned_start_sample


def test_before_first_after_final_and_one_cue_are_neutral(preview_source) -> None:
    document = preview_source.subtitle_document
    first = document.blocks[0]
    one = replace(document, blocks=(first,))
    sync = SubtitleSynchronizer(one)
    assert sync.block_at_sample(max(0, first.cleaned_start_sample - 1)) is None
    assert sync.block_at_sample(first.cleaned_start_sample) == first
    assert sync.block_at_sample(first.cleaned_end_sample) == first
    assert sync.block_at_sample(document.cleaned_total_samples - 1) == first
    assert sync.block_at_sample(document.cleaned_total_samples) is None
    cue = sync.cue_at_milliseconds(first.cleaned_start_sample * 1000 // document.sample_rate)
    assert cue is not None
    assert cue.cleaned_end_sample == first.cleaned_end_sample
    assert cue.display_end_sample == document.cleaned_total_samples


def test_malformed_overlap_is_rejected(preview_source) -> None:
    document = preview_source.subtitle_document
    first, second, *rest = document.blocks
    overlapping = replace(
        second,
        cleaned_start_sample=first.cleaned_end_sample - 1,
        duration_samples=second.cleaned_end_sample - (first.cleaned_end_sample - 1),
    )
    with pytest.raises(PreviewError):
        SubtitleSynchronizer(replace(document, blocks=(first, overlapping, *rest)))


def test_seeking_navigation_and_reload_keep_continuous_cue(preview_source) -> None:
    backend = FakeMediaBackend()
    controller = PreviewController(backend)
    controller.load(preview_source)
    first, second = preview_source.subtitle_document.blocks[:2]
    gap_sample = max(first.cleaned_start_sample, second.cleaned_start_sample - 1)
    controller.seek(gap_sample * 1000 // preview_source.sample_rate)
    assert controller.state.active_block_index == first.block_index
    controller.next_cue()
    assert backend.position == second.cleaned_start_sample * 1000 // preview_source.sample_rate
    controller.previous_cue()
    assert backend.position == first.cleaned_start_sample * 1000 // preview_source.sample_rate


def test_normal_preview_copy_contains_no_gap_error_strings(qapp) -> None:
    from larp_audio_mvp.gui.preview.widgets import PreviewPanel

    panel = PreviewPanel()
    visible = " ".join((panel.cue_label.text(), panel.cue_meta.text(), panel.warning_badge.text()))
    assert "No active subtitle" not in visible
    assert "Gap on cleaned timeline" not in visible
    assert "No cue warning" not in visible


def test_main_window_prepares_and_synchronizes_completed_run(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.alignment import read_alignment
    from larp_audio_mvp.gui.controller import GuiController
    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import GuiPhase, summarize_alignment

    request = make_request(tmp_path); result = make_service([]).run(request); backend = FakeMediaBackend()
    controller = GuiController()
    window = MainWindow(controller=controller, media_backend_factory=lambda: backend, settings=QSettings(str(tmp_path / "preview.ini"), QSettings.IniFormat))
    window.show(); qapp.processEvents()
    alignment = read_alignment(result.alignment_path)
    controller._publish(replace(
        controller.state, phase=GuiPhase.SUCCESS, source_audio_path=request.source_audio_path,
        script_input=request.script_input, local_model_path=request.local_model_path,
        output_directory=result.final_output_directory, pipeline_result=result,
        alignment=alignment, alignment_path=result.alignment_path,
        alignment_summary=summarize_alignment(alignment), progress_message="Voiceover package is ready.",
    ))
    _wait(qapp, lambda: window.preview_controller is not None and window.preview_controller.state.phase is PreviewPhase.READY)
    assert window.result_tabs.count() == 4
    assert window.export_button.isVisible()
    assert window.export_button.isEnabled()
    assert window.preview_panel.play_button.isEnabled()
    first = result.subtitle_document.blocks[0]
    backend.position_changed.emit(first.cleaned_start_sample * 1000 // result.subtitle_document.sample_rate)
    assert window.preview_controller.state.active_block_index == first.block_index
    backend.position_changed.emit(first.cleaned_end_sample * 1000 // result.subtitle_document.sample_rate)
    assert window.preview_controller.state.active_block_index == first.block_index
    backend.error_occurred.emit("PREVIEW_MEDIA_ERROR", "synthetic error")
    assert controller.state.phase is GuiPhase.SUCCESS
    assert controller.state.pipeline_result is result
    assert controller.state.active_failure is not None
    controller.dismiss_failure(); window.close(); qapp.processEvents()


def test_export_button_is_hidden_until_full_processing_succeeds(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.gui.main_window import MainWindow

    window = MainWindow(
        settings=QSettings(str(tmp_path / "export-button.ini"), QSettings.IniFormat),
        media_backend_factory=lambda: FakeMediaBackend(),
    )
    window.show()
    qapp.processEvents()
    assert not window.export_button.isVisible()
    assert window._export_dialog is None
    window.open_universal_export()
    assert window._export_dialog is None
    window.close()


def test_export_dialog_runs_in_worker_and_remembers_destination(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.alignment import read_alignment
    from larp_audio_mvp.gui.controller import GuiController
    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import GuiPhase, summarize_alignment

    request = make_request(tmp_path / "source")
    result = make_service([]).run(request)
    settings = QSettings(str(tmp_path / "export-prefs.ini"), QSettings.IniFormat)
    controller = GuiController()
    window = MainWindow(
        controller=controller,
        media_backend_factory=lambda: FakeMediaBackend(),
        settings=settings,
    )
    alignment = read_alignment(result.alignment_path)
    controller._publish(replace(
        controller.state,
        phase=GuiPhase.SUCCESS,
        source_audio_path=request.source_audio_path,
        script_input=request.script_input,
        local_model_path=request.local_model_path,
        output_directory=result.final_output_directory,
        pipeline_result=result,
        alignment=alignment,
        alignment_path=result.alignment_path,
        alignment_summary=summarize_alignment(alignment),
    ))
    _wait(qapp, lambda: window._preview_thread is None)
    window.open_universal_export()
    dialog = window._export_dialog
    assert dialog is not None
    destination = tmp_path / "universal exports"
    destination.mkdir()
    dialog.destination.setText(str(destination))
    dialog.base_name.setText("Campaign 01")
    dialog.start_export()
    assert dialog.worker_active
    _wait(qapp, lambda: not dialog.worker_active)
    assert dialog._pending is not None
    assert dialog._pending.audio_path.name == "Campaign 01_audio.wav"
    assert dialog._pending.subtitle_path.name == "Campaign 01_subtitles.srt"
    assert {path.name for path in destination.iterdir()} == {
        "Campaign 01_audio.wav", "Campaign 01_subtitles.srt"
    }
    assert settings.value("last_export_destination") == str(destination)
    assert not hasattr(dialog, "frame_rate")
    assert not hasattr(dialog, "target_buttons")
    dialog.accept()
    window.close()
