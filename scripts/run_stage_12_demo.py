"""Create the offline Stage 12 validated demo, diagnostics and Qt screenshots."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the offline Stage 12 preview demo.")
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser


def prepare(root: Path):
    from larp_audio_mvp.config import AlignmentSettings, AudioSettings, ModelSettings, SubtitleSettings, desktop_mvp_pause_settings
    from larp_audio_mvp.gui.preview import PreviewPreparationService
    from larp_audio_mvp.pipeline.contracts import PipelineRunRequest, ScriptSourceKind
    from larp_audio_mvp.pipeline.demo import create_synthetic_demo_service, write_synthetic_demo_wav
    from larp_audio_mvp.pipeline.script_input import load_script_input

    examples = root / "examples"; audio = examples / "stage_12_demo_input.wav"; script = examples / "stage_12_demo_script.txt"; output = examples / "stage_12_demo_output"
    write_synthetic_demo_wav(audio); script.write_bytes("Hello missing world.\r\nПривет, мир!\r\n".encode("utf-8"))
    shutil.rmtree(output, ignore_errors=True)
    model = root / "work" / "stage_12_demo_model"; model.mkdir(parents=True, exist_ok=True)
    try:
        script_input = load_script_input(script, source_kind=ScriptSourceKind.LOADED_FILE)
        request = PipelineRunRequest(
            audio.resolve(), script_input, model.resolve(), examples.resolve(), AudioSettings(), desktop_mvp_pause_settings(),
            ModelSettings(model_path=model.resolve(), whisper_model="tiny"), AlignmentSettings(),
            SubtitleSettings(max_words_per_block=2, minimum_timing_coverage_for_export="0.5"),
            "0.1.0", output_run_name="stage_12_demo_output",
        )
        result = create_synthetic_demo_service().run(request)
    finally:
        shutil.rmtree(model, ignore_errors=True)
    source = PreviewPreparationService().prepare(result)
    payload = {
        "schema_version": "preview_diagnostics.schema.v1", "run_id": source.run_id,
        "audio": {"sha256": source.audio_sha256, "sample_rate": source.sample_rate, "cleaned_total_samples": source.cleaned_total_samples},
        "subtitle_document_sha256": source.subtitle_document_sha256,
        "subtitle_block_count": len(source.subtitle_document.blocks),
        "warning_count": sum(bool(block.warnings) for block in source.subtitle_document.blocks),
        "timeline": "cleaned", "package_validation": source.diagnostics.package_valid,
        "provenance_validation": source.diagnostics.provenance_valid, "preview_available": True,
        "media_backend_capability": "fake backend available; Qt Multimedia checked separately",
        "entries": [{"section": item.section, "label": item.label, "value": item.value, "severity": item.severity.value} for item in source.diagnostics.entries],
    }
    (examples / "stage_12_preview_diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return audio, script, result, source, request


class FakeMediaBackend:
    def __init__(self):
        from larp_audio_mvp.gui.preview import EventHook
        from larp_audio_mvp.gui.preview.contracts import PlaybackState
        self.media_loaded=EventHook(); self.position_changed=EventHook(); self.duration_changed=EventHook(); self.playback_state_changed=EventHook(); self.media_status_changed=EventHook(); self.error_occurred=EventHook(); self._state=PlaybackState.STOPPED; self._duration=4_000
    def load(self, path): self.media_loaded.emit(); self.duration_changed.emit(self._duration)
    def play(self):
        from larp_audio_mvp.gui.preview.contracts import PlaybackState
        self._state=PlaybackState.PLAYING; self.playback_state_changed.emit(self._state)
    def pause(self):
        from larp_audio_mvp.gui.preview.contracts import PlaybackState
        self._state=PlaybackState.PAUSED; self.playback_state_changed.emit(self._state)
    def stop(self):
        from larp_audio_mvp.gui.preview.contracts import PlaybackState
        self._state=PlaybackState.STOPPED; self.playback_state_changed.emit(self._state)
    def seek(self, value): self.position_changed.emit(value)
    def set_volume(self, value): pass
    def set_muted(self, value): pass
    def current_position(self): return 0
    def duration(self): return self._duration
    def playback_state(self): return self._state
    def dispose(self): pass


def _save(window, path: Path, app) -> None:
    window.show(); window.repaint(); app.processEvents(); image = window.grab()
    if image.isNull() or image.width() < 1280 or image.height() < 900 or not image.save(str(path), "PNG"):
        raise RuntimeError(f"invalid screenshot: {path.name}")


def screenshots(root: Path, app, audio: Path, script: Path, result, source, request) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.alignment import read_alignment
    from larp_audio_mvp.gui.controller import GuiController
    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import AudioPreflightRequest, FailureSource, GuiFailure, GuiPhase, summarize_alignment
    from larp_audio_mvp.pipeline.contracts import PipelineCleanupOutcome

    examples=root/"examples"; backend=FakeMediaBackend(); controller=GuiController(); window=MainWindow(controller=controller, media_backend_factory=lambda: backend, settings=QSettings(str(root/"work"/"stage12-demo.ini"), QSettings.IniFormat)); window.resize(1280,900)
    controller.set_source_audio(Path("stage_12_demo_input.wav")); controller.set_script_input(replace(request.script_input, source_path=Path("stage_12_demo_script.txt"))); controller.set_local_model(Path("demo-local-model")); controller.set_output_directory(Path("demo-output")); window._model_valid=True
    window._updating_script_editor=True; window.script_editor.setPlainText(request.script_input.exact_text); window._updating_script_editor=False; window._update_script_counter(request.script_input)
    _save(window, examples/"stage_12_gui_input_layout.png", app)
    alignment=read_alignment(result.alignment_path); safe=Path("stage_12_demo_output"); safe_result=replace(result, final_output_directory=safe, cleaned_audio_path=safe/"cleaned_audio.wav", edit_map_path=safe/"edit_map.json", recognition_path=safe/"recognition.json", alignment_path=safe/"alignment.json", subtitle_blocks_path=safe/"subtitle_blocks.json", srt_path=safe/"subtitles.srt", processing_report_path=safe/"processing_report.json", manifest_path=safe/"manifest.json", package_zip_path=safe/"voiceover_package.zip")
    ready=replace(controller.state, phase=GuiPhase.SUCCESS, alignment=alignment, alignment_path=safe/"alignment.json", alignment_summary=summarize_alignment(alignment), pipeline_result=safe_result, active_failure=None, warnings=result.warnings, progress_message="Voiceover package is ready.")
    window._preview_requested_run_id=result.run_id; window.render_state(ready); window.preview_controller.load(source); window._populate_preview_diagnostics(source)
    for path in (result.cleaned_audio_path,result.edit_map_path,result.recognition_path,result.alignment_path,result.subtitle_blocks_path,result.srt_path,result.processing_report_path,result.manifest_path,result.package_zip_path): window.artifact_list.addItem(f"Validated · {path.name} · {path.stat().st_size:,} bytes")
    scroll=window.centralWidget().verticalScrollBar(); scroll.setValue(scroll.maximum()); app.processEvents()
    window.result_tabs.setCurrentIndex(0); _save(window, examples/"stage_12_gui_preview_ready.png", app)
    backend.play(); backend.position_changed.emit(source.subtitle_document.blocks[0].cleaned_start_sample*1000//source.sample_rate); _save(window, examples/"stage_12_gui_preview_playing.png", app)
    second=source.subtitle_document.blocks[1]; third=source.subtitle_document.blocks[2]; backend.position_changed.emit((second.cleaned_end_sample+100)*1000//source.sample_rate); _save(window, examples/"stage_12_gui_preview_gap.png", app)
    backend.position_changed.emit(source.subtitle_document.blocks[0].cleaned_start_sample*1000//source.sample_rate); _save(window, examples/"stage_12_gui_preview_warning.png", app)
    window.result_tabs.setCurrentIndex(2); _save(window, examples/"stage_12_gui_diagnostics.png", app)
    window.result_tabs.setCurrentIndex(3); _save(window, examples/"stage_12_gui_artifacts.png", app)
    window.result_tabs.setCurrentIndex(0); backend.error_occurred.emit("PREVIEW_MEDIA_ERROR","Synthetic local media error"); _save(window, examples/"stage_12_gui_preview_error.png", app)
    scroll.setValue(0); stale=AudioPreflightRequest("audio-C",Path("new_audio_C.wav"),"new_audio_C.wav",3); controller.begin_audio_preflight(stale); window.render_state(controller.state); _save(window, examples/"stage_12_gui_stale_preflight_protected.png", app)
    cleanup=PipelineCleanupOutcome(True,False,".demo.partial",True,"PIPELINE_CLEANUP_FAILED","Workspace remains.",manual_cleanup_may_be_required=True,residual_workspace_path=Path(".demo.partial")); failure=GuiFailure("Audio processing failed","Synthetic failure","SYNTHETIC_FAILURE","Temporary workspace remains; manual cleanup may be required.",Path(".demo.partial"),source=FailureSource.FULL_PIPELINE,cleanup_outcome=cleanup); window.render_state(replace(ready,active_failure=failure,progress_message="Processing failed; cleanup incomplete.")); _save(window, examples/"stage_12_gui_cleanup_failure.png", app)
    window.render_state(ready); window.close(); app.processEvents()


def main(argv=None) -> int:
    args=_parser().parse_args(argv)
    if args.screenshots or args.smoke: os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    root=Path(__file__).resolve().parents[1]; (root/"work").mkdir(exist_ok=True); audio,script,result,source,request=prepare(root)
    if args.screenshots or args.smoke:
        from larp_audio_mvp.gui.application import create_application
        app=create_application([sys.argv[0]])
        if args.screenshots: screenshots(root,app,audio,script,result,source,request)
        if args.smoke:
            from PySide6.QtCore import QTimer
            from PySide6.QtCore import QSettings
            from larp_audio_mvp.gui.main_window import MainWindow
            window=MainWindow(media_backend_factory=FakeMediaBackend,settings=QSettings(str(root/"work"/"stage12-smoke.ini"),QSettings.IniFormat)); window.resize(1280,900); window.show(); QTimer.singleShot(250,app.quit); return app.exec()
    print(result.final_output_directory); return 0


if __name__ == "__main__": raise SystemExit(main())
