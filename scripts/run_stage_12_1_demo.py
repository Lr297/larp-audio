"""Generate real production Stage 12.1 one-page GUI screenshots."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Stage 12.1 production GUI demo.")
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser


def _save(window, path: Path, app, *, bottom: bool = False) -> None:
    window.show(); window.repaint(); app.processEvents()
    if bottom:
        bar = window.main_scroll_area.verticalScrollBar(); bar.setValue(bar.maximum()); app.processEvents()
    image = window.grab()
    if image.isNull() or image.width() < 1100 or image.height() < 760 or not image.save(str(path), "PNG"):
        raise RuntimeError(f"invalid production screenshot: {path.name}")


def _save_dialog(window, dialog, path: Path, app) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter, QPixmap
    window.show(); dialog.show(); window.repaint(); dialog.repaint(); app.processEvents()
    canvas = QPixmap(window.size()); canvas.fill(); painter = QPainter(canvas)
    try:
        window.render(painter, QPoint(0, 0))
        x = (window.width() - dialog.width()) // 2; y = (window.height() - dialog.height()) // 2
        dialog.render(painter, QPoint(x, y))
    finally:
        painter.end()
    if canvas.isNull() or not canvas.save(str(path), "PNG"): raise RuntimeError(path.name)
    dialog.close(); app.processEvents()


def screenshots(root: Path, app) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.alignment import read_alignment
    from larp_audio_mvp.gui.controller import GuiController
    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import AudioPreflightRequest, AudioPreflightResult, FailureSource, GuiFailure, GuiPhase, summarize_alignment
    from larp_audio_mvp.pipeline.contracts import PipelineProgress, PipelineStage
    from larp_audio_mvp.pipeline.demo import _audio_info
    from run_stage_12_demo import FakeMediaBackend, prepare

    examples = root / "examples"; audio, script, result, source, request = prepare(root); backend = FakeMediaBackend(); controller = GuiController(); settings = QSettings(str(root / "work" / "stage12-1-demo.ini"), QSettings.IniFormat); settings.clear(); settings.sync()
    window = MainWindow(controller=controller, media_backend_factory=lambda: backend, settings=settings); window.resize(1440, 900); window.main_scroll_area.verticalScrollBar().setValue(0)
    _save(window, examples / "stage_12_1_create_empty.png", app)

    identity = str(audio.resolve()); preflight = AudioPreflightRequest("stage121-audio", audio, identity, 1); controller.begin_audio_preflight(preflight); controller.apply_audio_preflight_result(AudioPreflightResult(preflight.request_id, audio, identity, _audio_info(audio)))
    safe_script = replace(request.script_input, source_path=Path("stage_12_demo_script.txt")); controller.set_script_input(safe_script); controller.set_local_model(Path("demo-speech-model")); controller.set_output_directory(Path("demo-results")); window._model_valid = True; window.model_status.setText("Ready · tiny · cpu"); window._updating_script_editor = True; window.script_editor.setPlainText(safe_script.exact_text); window._updating_script_editor = False; window._update_script_counter(safe_script); window.render_state(controller.state)
    _save(window, examples / "stage_12_1_create_ready.png", app)
    _save_dialog(window, window.advanced_dialog, examples / "stage_12_1_advanced_settings.png", app)

    progress = PipelineProgress(PipelineStage.RECOGNIZING_SPEECH, 8, 14, "Recognizing speech")
    processing = replace(controller.state, phase=GuiPhase.PROCESSING, task_active=True, pipeline_progress=progress, progress_message="Recognizing speech")
    window.render_state(processing); _save(window, examples / "stage_12_1_processing.png", app, bottom=True)

    alignment = read_alignment(result.alignment_path); success = replace(controller.state, phase=GuiPhase.SUCCESS, alignment=alignment, alignment_path=result.alignment_path, alignment_summary=summarize_alignment(alignment), pipeline_result=result, warnings=result.warnings, progress_message="Result ready")
    window._preview_requested_run_id = result.run_id; controller._publish(success); window.preview_controller.load(source); window._populate_preview_diagnostics(source); window._populate_artifacts(); backend.position_changed.emit(source.subtitle_document.blocks[0].cleaned_start_sample * 1000 // source.sample_rate)
    scroll = window.main_scroll_area.verticalScrollBar(); window.result_tabs.setCurrentIndex(0); _save(window, examples / "stage_12_1_preview.png", app, bottom=True)
    window.result_tabs.setCurrentIndex(1); _save(window, examples / "stage_12_1_subtitle_blocks.png", app, bottom=True)
    window.result_tabs.setCurrentIndex(2); _save(window, examples / "stage_12_1_diagnostics.png", app, bottom=True)
    window.result_tabs.setCurrentIndex(3); _save(window, examples / "stage_12_1_files.png", app, bottom=True)
    window.result_tabs.setCurrentIndex(0); backend.error_occurred.emit("PREVIEW_MEDIA_ERROR", "The local media service could not play this file."); _save(window, examples / "stage_12_1_error.png", app, bottom=True); controller.dismiss_failure()

    window.start_over(); window.resize(1100, 760); scroll.setValue(0); app.processEvents(); _save(window, examples / "stage_12_1_1100x760.png", app)
    window.resize(1440, 900); app.processEvents(); _save(window, examples / "stage_12_1_1440x900.png", app)
    window.close(); app.processEvents()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv); os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); root = Path(__file__).resolve().parents[1]; (root / "work").mkdir(exist_ok=True)
    from larp_audio_mvp.gui.application import create_application
    app = create_application([sys.argv[0]])
    if args.screenshots: screenshots(root, app)
    if args.smoke:
        from PySide6.QtCore import QSettings, QTimer
        from larp_audio_mvp.gui.main_window import MainWindow
        from run_stage_12_demo import FakeMediaBackend
        window = MainWindow(media_backend_factory=FakeMediaBackend, settings=QSettings(str(root / "work" / "stage12-1-smoke.ini"), QSettings.IniFormat)); window.show(); QTimer.singleShot(300, app.quit); return app.exec()
    return 0


if __name__ == "__main__": raise SystemExit(main())
