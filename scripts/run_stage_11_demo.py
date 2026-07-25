"""Generate the synthetic full-pipeline demo and capture real Qt GUI states."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the fully offline Stage 11 synthetic demo.")
    value.add_argument("--screenshots", action="store_true")
    value.add_argument("--smoke", action="store_true")
    return value


def prepare_demo(root: Path):
    from larp_audio_mvp.config import AlignmentSettings, AudioSettings, ModelSettings, PauseSettings, SubtitleSettings
    from larp_audio_mvp.pipeline.contracts import PipelineRunRequest, ScriptSourceKind
    from larp_audio_mvp.pipeline.demo import create_synthetic_demo_service, write_synthetic_demo_wav
    from larp_audio_mvp.pipeline.script_input import load_script_input

    examples = root / "examples"
    audio = examples / "stage_11_demo_input.wav"
    script = examples / "stage_11_demo_script.txt"
    write_synthetic_demo_wav(audio)
    script.write_bytes("Hello missing world.\nПривет, мир!\n".encode("utf-8"))
    output = examples / "stage_11_demo_output"
    if output.exists():
        shutil.rmtree(output)
    with tempfile.TemporaryDirectory(prefix="stage-11-model-", dir=root / "work") as raw_model:
        model = Path(raw_model)
        request = PipelineRunRequest(
            audio.resolve(), load_script_input(script), model.resolve(), examples.resolve(),
            AudioSettings(),
            PauseSettings(silence_threshold_db=Decimal("-50"), minimum_pause_duration_ms=300, shortening_policy_version="synthetic-demo-v1", minimum_pause_to_shorten_ms=500, target_remaining_pause_ms=200, maximum_removed_per_pause_ms=1_000),
            ModelSettings(model_path=model.resolve(), whisper_model="tiny"),
            AlignmentSettings(), SubtitleSettings(minimum_timing_coverage_for_export=Decimal("0.5")), "0.1.0",
            output_run_name="stage_11_demo_output",
        )
        result = create_synthetic_demo_service().run(request)
    return audio, script, result


def save(window, path: Path, application) -> None:
    window.show(); window.repaint(); application.processEvents()
    image = window.grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Cannot save {path}")


def screenshots(root: Path, application, audio: Path, script: Path, result) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.gui.controller import GuiController
    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import FailureSource, GuiFailure, GuiPhase
    from larp_audio_mvp.pipeline.script_input import load_script_input

    examples = root / "examples"
    controller = GuiController(full_service_factory=lambda request: __import__("larp_audio_mvp.pipeline.demo", fromlist=["create_synthetic_demo_service"]).create_synthetic_demo_service())
    window = MainWindow(controller=controller, settings=QSettings(str(root / "work" / "stage11-demo.ini"), QSettings.IniFormat))
    window.resize(1280, 900)
    save(window, examples / "stage_11_gui_empty.png", application)
    script_input = load_script_input(script)
    model_display = Path("demo-local-model")
    controller.set_source_audio(Path("examples/stage_11_demo_input.wav")); controller.set_script_input(script_input); controller.set_local_model(model_display); controller.set_output_directory(Path("examples"))
    window._model_valid = True; window.model_status.setText("Ready · synthetic local model")
    window._updating_script_editor = True; window.script_editor.setPlainText(script_input.exact_text); window._updating_script_editor = False; window._update_script_counter(script_input)
    ready = controller.state
    window.render_state(ready); save(window, examples / "stage_11_gui_input_ready.png", application)
    for phase, filename, message in (
        (GuiPhase.PREFLIGHTING, "stage_11_gui_preflighting.png", "Step 1 of 14: Checking local inputs, model, and media tools"),
        (GuiPhase.PROCESSING, "stage_11_gui_processing.png", "Step 8 of 14: Running local Faster-Whisper word timing"),
        (GuiPhase.CANCELLING, "stage_11_gui_cancelling.png", "Cancel requested — stopping after the current safe step."),
        (GuiPhase.FINISHING, "stage_11_gui_finishing.png", "Finalizing and cleaning up the background task…"),
    ):
        window.render_state(replace(ready, phase=phase, task_active=True, progress_message=message)); save(window, examples / filename, application)
    alignment = __import__("larp_audio_mvp.alignment", fromlist=["read_alignment"]).read_alignment(result.alignment_path)
    success = replace(ready, phase=GuiPhase.SUCCESS, task_active=False, alignment=alignment, alignment_path=result.alignment_path, alignment_summary=__import__("larp_audio_mvp.gui.state", fromlist=["summarize_alignment"]).summarize_alignment(alignment), pipeline_result=result, warnings=result.warnings, progress_message="Voiceover package is ready.")
    window.render_state(success); save(window, examples / "stage_11_gui_success.png", application)
    failure = GuiFailure("Local model is not ready", "Select a complete local Faster-Whisper model folder.", "LOCAL_WHISPER_MODEL_INVALID", details="No network fallback or automatic download is allowed.", related_path=model_display, source=FailureSource.SETTINGS_VALIDATION)
    window.render_state(replace(ready, active_failure=failure)); save(window, examples / "stage_11_gui_failure.png", application)
    window.close(); application.processEvents()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.screenshots or args.smoke: os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]; (root / "work").mkdir(exist_ok=True)
    audio, script, result = prepare_demo(root)
    if args.screenshots or args.smoke:
        from larp_audio_mvp.gui.application import create_application
        application = create_application([sys.argv[0]])
        if args.screenshots: screenshots(root, application, audio, script, result)
        if args.smoke:
            from PySide6.QtCore import QSettings, QTimer
            from larp_audio_mvp.gui.main_window import MainWindow
            window = MainWindow(settings=QSettings(str(root / "work" / "stage11-smoke.ini"), QSettings.IniFormat)); window.show(); QTimer.singleShot(250, application.quit); return application.exec()
    print(result.final_output_directory)
    return 0


if __name__ == "__main__": raise SystemExit(main())
