"""Generate Stage 11.1 artifacts, factual cleanup fixtures, and real Qt screenshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the offline Stage 11.1 correction demo.")
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser


def _json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def prepare(root: Path):
    from larp_audio_mvp.config import AlignmentSettings, AudioSettings, ModelSettings, SubtitleSettings, desktop_mvp_pause_settings
    from larp_audio_mvp.pipeline.artifacts import sha256_file, validate_package
    from larp_audio_mvp.pipeline.contracts import PipelineRunRequest, ScriptSourceKind
    from larp_audio_mvp.pipeline.demo import create_synthetic_demo_service, write_synthetic_demo_wav
    from larp_audio_mvp.pipeline.privacy import validate_published_artifact_privacy
    from larp_audio_mvp.pipeline.script_input import load_script_input
    from larp_audio_mvp.pipeline.validation import validate_pipeline_artifact_set

    examples = root / "examples"
    audio = examples / "stage_11_1_demo_input.wav"
    script = examples / "stage_11_1_demo_script.txt"
    output = examples / "stage_11_1_demo_output"
    write_synthetic_demo_wav(audio)
    script.write_bytes("Hello missing world.\r\nПривет, мир!\r\n".encode("utf-8"))
    if output.exists():
        shutil.rmtree(output)
    model = root / "work" / "stage_11_1_demo_model"
    model.mkdir(exist_ok=True)
    try:
        script_input = load_script_input(script, source_kind=ScriptSourceKind.LOADED_FILE)
        request = PipelineRunRequest(
            audio.resolve(), script_input, model.resolve(), examples.resolve(),
            AudioSettings(), desktop_mvp_pause_settings(),
            ModelSettings(model_path=model.resolve(), whisper_model="tiny"),
            AlignmentSettings(), SubtitleSettings(minimum_timing_coverage_for_export="0.5"),
            "0.1.0", output_run_name="stage_11_1_demo_output",
        )
        result = create_synthetic_demo_service().run(request)
    finally:
        shutil.rmtree(model, ignore_errors=True)

    validated = validate_pipeline_artifact_set(
        result.final_output_directory,
        audio_settings=request.audio_settings,
        expected_script_text=script_input.exact_text,
        expected_script_sha256=script_input.sha256,
        expected_source_audio_sha256=sha256_file(audio),
        forbidden_paths=(root, Path.home(), request.local_model_path),
        include_report=True,
        include_manifest=True,
    )
    validate_published_artifact_privacy(
        result.final_output_directory.glob("*.json"),
        forbidden_paths=(root, Path.home(), request.local_model_path),
    )
    validate_package(result.package_zip_path)

    _json(examples / "stage_11_1_cleanup_success.json", {
        "schema_version": "pipeline_cleanup_outcome.schema.v1", "primary_error_code": "SYNTHETIC_PRIMARY_FAILURE",
        "cleanup": {"attempted": True, "completed": True, "residual_workspace_exists": False, "error_code": None, "manual_cleanup_may_be_required": False, "staging_path_safe_display": ".demo.partial"},
    })
    _json(examples / "stage_11_1_cleanup_failure.json", {
        "schema_version": "pipeline_cleanup_outcome.schema.v1", "primary_error_code": "SYNTHETIC_PRIMARY_FAILURE",
        "cleanup": {"attempted": True, "completed": False, "residual_workspace_exists": True, "error_code": "PIPELINE_CLEANUP_FAILED", "manual_cleanup_may_be_required": True, "staging_path_safe_display": ".demo.partial"},
    })
    json_files = sorted(path.name for path in result.final_output_directory.glob("*.json"))
    _json(examples / "stage_11_1_privacy_scan.json", {
        "schema_version": "privacy_scan.schema.v1", "passed": True,
        "absolute_paths_found": 0, "files": json_files + ["voiceover_package.zip"],
    })
    _json(examples / "stage_11_1_provenance_validation.json", {
        "schema_version": "pipeline_provenance_validation.schema.v1", "passed": True,
        "cleaned_audio_sha256": validated.cleaned_audio.sha256,
        "edit_map_output_sha256": validated.edit_map.output_sha256,
        "script_sha256": validated.alignment.script.source_sha256,
        "source_audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "sample_rate": validated.edit_map.sample_rate,
        "source_total_samples": validated.edit_map.source_total_samples,
        "cleaned_total_samples": validated.edit_map.output_total_samples,
    })
    return audio, script, result


def _save(window, path: Path, application) -> None:
    window.show(); window.repaint(); application.processEvents()
    image = window.grab()
    if image.isNull() or image.width() < 1200 or image.height() < 760 or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Cannot save a valid screenshot: {path.name}")


def screenshots(root: Path, application, script: Path, result) -> None:
    from PySide6.QtCore import QSettings
    from larp_audio_mvp.alignment import read_alignment
    from larp_audio_mvp.gui.controller import GuiController
    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import FailureSource, GuiFailure, GuiPhase, summarize_alignment
    from larp_audio_mvp.pipeline.contracts import PipelineCleanupOutcome
    from larp_audio_mvp.pipeline.script_input import load_script_input

    examples = root / "examples"
    controller = GuiController(full_service_factory=lambda _request: None)
    window = MainWindow(controller=controller, settings=QSettings(str(root / "work" / "stage11-1-demo.ini"), QSettings.IniFormat))
    window.resize(1280, 900)
    script_input = load_script_input(script)
    safe_script = replace(script_input, source_path=Path("stage_11_1_demo_script.txt"))
    controller.set_source_audio(Path("stage_11_1_demo_input.wav")); controller.set_script_input(safe_script)
    controller.set_local_model(Path("demo-local-model")); controller.set_output_directory(Path("demo-outputs"))
    window._model_valid = True; window._audio_preflight_ready = True
    window.model_status.setText("Ready · synthetic local model")
    window.audio_preflight_status.setText("wav · 4.00 s · 48000 Hz · 1 ch · pcm_s16le · 384,044 bytes")
    window._updating_script_editor = True; window.script_editor.setPlainText(safe_script.exact_text); window._updating_script_editor = False; window._update_script_counter(safe_script)
    ready = controller.state
    states = (
        ("stage_11_1_gui_preflight.png", GuiPhase.PREFLIGHTING, "Step 1 of 14: Checking local inputs, path safety, model, and media tools"),
        ("stage_11_1_gui_canonicalizing.png", GuiPhase.PROCESSING, "Step 4 of 14: Creating canonical mono 48 kHz PCM WAV"),
        ("stage_11_1_gui_rendering.png", GuiPhase.PROCESSING, "Step 7 of 14: Rendering cleaned audio from the edit map"),
    )
    for filename, phase, message in states:
        window.render_state(replace(ready, phase=phase, task_active=True, progress_message=message))
        _save(window, examples / filename, application)

    cleanup = PipelineCleanupOutcome(True, False, ".demo.partial", True, "PIPELINE_CLEANUP_FAILED", "Temporary workspace could not be fully removed.", manual_cleanup_may_be_required=True, residual_workspace_path=Path(".demo.partial"))
    failure = GuiFailure("Audio processing failed", "Synthetic recognition failure", "SYNTHETIC_PRIMARY_FAILURE", "Failed stage: recognizing_speech. Manual cleanup may be required.", Path(".demo.partial"), source=FailureSource.FULL_PIPELINE, cleanup_outcome=cleanup)
    window.render_state(replace(ready, active_failure=failure, progress_message="Processing failed. Temporary workspace could not be fully removed."))
    _save(window, examples / "stage_11_1_gui_cleanup_failure.png", application)

    alignment = read_alignment(result.alignment_path)
    safe_root = Path("stage_11_1_demo_output")
    safe_result = replace(
        result, final_output_directory=safe_root, cleaned_audio_path=safe_root / "cleaned_audio.wav",
        edit_map_path=safe_root / "edit_map.json", recognition_path=safe_root / "recognition.json",
        alignment_path=safe_root / "alignment.json", subtitle_blocks_path=safe_root / "subtitle_blocks.json",
        srt_path=safe_root / "subtitles.srt", processing_report_path=safe_root / "processing_report.json",
        manifest_path=safe_root / "manifest.json", package_zip_path=safe_root / "voiceover_package.zip",
    )
    success = replace(ready, phase=GuiPhase.SUCCESS, task_active=False, alignment=alignment, alignment_path=safe_root / "alignment.json", alignment_summary=summarize_alignment(alignment), pipeline_result=safe_result, active_failure=None, warnings=result.warnings, progress_message="Voiceover package is ready.")
    window.render_state(success)
    _save(window, examples / "stage_11_1_gui_success.png", application)
    window.close(); application.processEvents()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.screenshots or args.smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    (root / "work").mkdir(exist_ok=True)
    _audio, script, result = prepare(root)
    if args.screenshots or args.smoke:
        from larp_audio_mvp.gui.application import create_application
        application = create_application([sys.argv[0]])
        if args.screenshots:
            screenshots(root, application, script, result)
        if args.smoke:
            from PySide6.QtCore import QSettings, QTimer
            from larp_audio_mvp.gui.main_window import MainWindow
            window = MainWindow(settings=QSettings(str(root / "work" / "stage11-1-smoke.ini"), QSettings.IniFormat))
            window.resize(1200, 760); window.show(); QTimer.singleShot(250, application.quit)
            return application.exec()
    print(result.final_output_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
