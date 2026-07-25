"""Prepare Stage 10.1 demo outputs, launch the GUI, or capture real widgets."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the Stage 10.1 subtitle GUI demo.")
    parser.add_argument("--screenshots", action="store_true", help="Capture all required offscreen GUI states and exit.")
    parser.add_argument("--smoke", action="store_true", help="Open the ready-state window briefly and exit.")
    return parser


def prepare_demo(root: Path) -> tuple[Path, Path, Path]:
    from larp_audio_mvp.alignment import read_alignment, write_alignment_atomic
    from larp_audio_mvp.config import SubtitleSettings
    from larp_audio_mvp.gui.state import FailureSource, GuiFailure, format_failure_details
    from larp_audio_mvp.subtitles.service import SubtitleGenerationService

    examples = root / "examples"
    source = read_alignment(examples / "stage_9_1_example_alignment.json")
    synthetic_script = replace(
        source.script, source_path=Path("synthetic/stage_10_1_demo_script.txt")
    )
    demo = replace(source, script=synthetic_script)
    alignment = examples / "stage_10_1_demo_alignment.json"
    blocks = examples / "stage_10_1_demo_subtitle_blocks.json"
    srt = examples / "stage_10_1_demo_subtitles.srt"
    write_alignment_atomic(demo, alignment)
    SubtitleGenerationService().generate(
        alignment_path=alignment,
        blocks_output=blocks,
        srt_output=srt,
        settings=SubtitleSettings(),
    )
    failure = GuiFailure(
        title="Output folder could not be opened",
        message="The operating system rejected the desktop action.",
        error_code="DESKTOP_OPEN_FAILED",
        details="The generated subtitle result is still available.",
        related_path=Path("demo-output"),
        source=FailureSource.DESKTOP_ACTION,
    )
    (examples / "stage_10_1_error_details.txt").write_text(
        format_failure_details(failure) + "\n", encoding="utf-8", newline=""
    )
    return alignment, blocks, srt


def _wait(application, predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise RuntimeError("GUI demo operation timed out")


def _save(window, path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    window.show()
    window.repaint()
    QApplication.processEvents()
    image = window.grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"cannot save GUI screenshot: {path}")


def capture_screenshots(root: Path, application, alignment: Path) -> None:
    from PySide6.QtCore import QSettings

    from larp_audio_mvp.gui.main_window import MainWindow
    from larp_audio_mvp.gui.state import FailureSource, GuiFailure, GuiPhase

    examples = root / "examples"
    with tempfile.TemporaryDirectory(prefix="stage-10-1-gui-", dir=root / "work") as raw:
        temporary = Path(raw)
        window = MainWindow(settings=QSettings(str(temporary / "demo.ini"), QSettings.IniFormat))
        window.resize(1200, 760)
        _save(window, examples / "stage_10_1_gui_empty.png")

        window.controller.load_alignment(alignment)
        application.processEvents()
        ready_display = replace(
            window.controller.state,
            alignment_path=Path("examples/stage_10_1_demo_alignment.json"),
            output_directory=Path("demo-output"),
        )
        window.render_state(ready_display)
        _save(window, examples / "stage_10_1_gui_ready.png")

        window.render_state(replace(ready_display, phase=GuiPhase.PROCESSING, task_active=True, progress_message="Building subtitle blocks"))
        _save(window, examples / "stage_10_1_gui_processing.png")
        window.render_state(replace(ready_display, phase=GuiPhase.FINISHING, task_active=True, progress_message="Finalizing and cleaning up the background task…"))
        _save(window, examples / "stage_10_1_gui_finishing.png")

        window.render_state(window.controller.state)
        window.controller.set_output_directory(temporary / "output")
        if not window.controller.generate(window.subtitle_settings()):
            raise RuntimeError("demo GUI generation did not start")
        _wait(application, lambda: window.controller.state.phase is GuiPhase.SUCCESS)
        success_display = replace(
            window.controller.state,
            alignment_path=Path("examples/stage_10_1_demo_alignment.json"),
            output_directory=Path("demo-output"),
        )
        window.render_state(success_display)
        _save(window, examples / "stage_10_1_gui_success.png")

        failure = GuiFailure(
            title="Output folder could not be opened",
            message="The operating system rejected the desktop action.",
            error_code="DESKTOP_OPEN_FAILED",
            details="The generated subtitle result is still available.",
            related_path=Path("demo-output"),
            source=FailureSource.DESKTOP_ACTION,
        )
        window.render_state(replace(success_display, active_failure=failure))
        _save(window, examples / "stage_10_1_gui_recoverable_error.png")

        window.render_state(success_display)
        window.show_warnings_only.setChecked(True)
        application.processEvents()
        _save(window, examples / "stage_10_1_gui_warning_filter.png")
        window.close()
        application.processEvents()


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.screenshots:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    (root / "work").mkdir(parents=True, exist_ok=True)
    alignment, _, _ = prepare_demo(root)

    from PySide6.QtCore import QSettings, QTimer
    from larp_audio_mvp.gui.application import create_application
    from larp_audio_mvp.gui.main_window import MainWindow

    application = create_application([sys.argv[0]])
    if arguments.screenshots:
        capture_screenshots(root, application, alignment)
        return 0
    window = MainWindow(settings=QSettings(str(root / "work" / "demo_gui.ini"), QSettings.IniFormat))
    window.controller.load_alignment(alignment)
    window.show()
    if arguments.smoke:
        QTimer.singleShot(350, application.quit)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
