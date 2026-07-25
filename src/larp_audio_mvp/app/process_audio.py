"""CLI for the same complete local workflow used by the desktop application."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from larp_audio_mvp.config import (
    AlignmentSettings,
    AudioSettings,
    ModelSettings,
    PauseSettings,
    SubtitleSettings,
)
from larp_audio_mvp.core.errors import PipelineCancellationError, ProjectError
from larp_audio_mvp.pipeline.contracts import PipelineProgress, PipelineRunRequest, ScriptSourceKind
from larp_audio_mvp.pipeline.factory import create_full_processing_service
from larp_audio_mvp.pipeline.failures import PipelineCancelledFailure, PipelineRunFailure
from larp_audio_mvp.pipeline.script_input import create_script_input, load_script_input
from larp_audio_mvp.version import RELEASE_VERSION


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a complete local voiceover subtitle package.")
    parser.add_argument("--audio", type=Path, required=True)
    script = parser.add_mutually_exclusive_group(required=True)
    script.add_argument("--script-file", type=Path)
    script.add_argument("--script-stdin", action="store_true")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model", choices=("tiny", "base", "small"), required=True)
    parser.add_argument("--output-parent", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--language")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--silence-threshold-db", type=Decimal, default=Decimal("-50"))
    parser.add_argument("--minimum-pause-duration-ms", type=int, default=300)
    parser.add_argument("--minimum-pause-to-shorten-ms", type=int, default=500)
    parser.add_argument("--target-remaining-pause-ms", type=int, default=200)
    parser.add_argument("--maximum-removed-per-pause-ms", type=int, default=1_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.script_file is not None:
            script_input = load_script_input(args.script_file, source_kind=ScriptSourceKind.CLI_FILE)
        else:
            text = sys.stdin.read(500_001)
            script_input = create_script_input(text, source_kind=ScriptSourceKind.STDIN)
        audio_settings = AudioSettings()
        pause_settings = PauseSettings(
            silence_threshold_db=args.silence_threshold_db,
            minimum_pause_duration_ms=args.minimum_pause_duration_ms,
            shortening_policy_version="desktop-mvp-v1",
            minimum_pause_to_shorten_ms=args.minimum_pause_to_shorten_ms,
            target_remaining_pause_ms=args.target_remaining_pause_ms,
            maximum_removed_per_pause_ms=args.maximum_removed_per_pause_ms,
        )
        model_path = args.model_path.expanduser().resolve()
        model_settings = ModelSettings(
            model_path=model_path,
            whisper_model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            beam_size=args.beam_size,
        )
        request = PipelineRunRequest(
            source_audio_path=args.audio.expanduser().resolve(),
            script_input=script_input,
            local_model_path=model_path,
            output_parent_directory=args.output_parent.expanduser().resolve(),
            audio_settings=audio_settings,
            pause_settings=pause_settings,
            recognition_settings=model_settings,
            alignment_settings=AlignmentSettings(),
            subtitle_settings=SubtitleSettings(),
            application_version=RELEASE_VERSION,
        )
        service = create_full_processing_service(
            audio_settings=audio_settings,
            pause_settings=pause_settings,
            alignment_settings=request.alignment_settings,
            ffmpeg_path=args.ffmpeg,
            ffprobe_path=args.ffprobe,
        )

        def progress(item: PipelineProgress) -> None:
            print(f"[{item.stage_index}/{item.total_stages}] {item.stage.value}: {item.message}", file=sys.stderr)

        result = service.run(request, progress=progress)
        summary = result.summary
        print(json.dumps({
            "run_id": result.run_id,
            "output_directory": str(result.final_output_directory),
            "cleaned_audio_path": str(result.cleaned_audio_path),
            "srt_path": str(result.srt_path),
            "subtitle_blocks_path": str(result.subtitle_blocks_path),
            "edit_map_path": str(result.edit_map_path),
            "recognition_path": str(result.recognition_path),
            "alignment_path": str(result.alignment_path),
            "processing_report_path": str(result.processing_report_path),
            "manifest_path": str(result.manifest_path),
            "package_zip_path": str(result.package_zip_path),
            "source_duration_samples": summary.source_duration_samples,
            "cleaned_duration_samples": summary.cleaned_duration_samples,
            "removed_samples": summary.removed_samples,
            "subtitle_block_count": summary.subtitle_block_count,
            "text_coverage": f"{summary.text_coverage.numerator}/{summary.text_coverage.denominator}",
            "timing_coverage": f"{summary.timing_coverage.numerator}/{summary.timing_coverage.denominator}",
            "warnings_count": len(result.warnings),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except PipelineCancelledFailure as exc:
        _print_pipeline_failure(exc)
        return 3
    except PipelineRunFailure as exc:
        _print_pipeline_failure(exc)
        return 2
    except PipelineCancellationError as exc:
        print(f"primary_error_code={exc.code}\nmessage={exc}", file=sys.stderr)
        return 3
    except ProjectError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2


def _print_pipeline_failure(exc: PipelineRunFailure | PipelineCancelledFailure) -> None:
    cleanup = exc.cleanup_outcome
    lines = (
        f"primary_error_code={exc.code}",
        f"message={exc.primary_error}",
        f"failed_stage={exc.failed_stage.value}",
        f"cleanup_attempted={str(cleanup.attempted).lower()}",
        f"cleanup_completed={str(cleanup.completed).lower()}",
        f"residual_workspace_exists={str(cleanup.residual_workspace_exists).lower()}",
        f"secondary_error_code={cleanup.error_code or ''}",
        f"manual_cleanup_may_be_required={str(cleanup.manual_cleanup_may_be_required).lower()}",
    )
    print("\n".join(lines), file=sys.stderr)
    if cleanup.residual_workspace_exists and cleanup.residual_workspace_path is not None:
        print(f"residual_workspace_path={cleanup.residual_workspace_path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
