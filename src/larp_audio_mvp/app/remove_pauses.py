"""Developer CLI for pause detection, edit-map creation, and WAV rendering."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.audio import (
    EditMapBuilder,
    ExecutableResolver,
    FfmpegPauseDetector,
    FfmpegWavRenderer,
    FfprobeAdapter,
    PauseRemovalService,
    PauseShorteningPolicy,
    SubprocessRunner,
)
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.config import AudioSettings, PauseSettings
from larp_audio_mvp.core.contracts import EditKind
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import configure_logging, get_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shorten detected pause middles and create edit_map.json."
    )
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--work-directory", type=Path, required=True)
    parser.add_argument(
        "--silence-threshold-db", type=_decimal_argument, required=True
    )
    parser.add_argument("--minimum-pause-duration-ms", type=int, required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--minimum-pause-to-shorten-ms", type=int, required=True)
    parser.add_argument("--target-remaining-pause-ms", type=int, required=True)
    parser.add_argument("--maximum-removed-per-pause-ms", type=int, required=True)
    parser.add_argument("--ffmpeg", type=Path, default=None)
    parser.add_argument("--ffprobe", type=Path, default=None)
    parser.add_argument("--bundled-tools-directory", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    configure_logging()
    logger = get_logger("app.remove_pauses")
    try:
        audio_settings = AudioSettings(
            subprocess_timeout_seconds=arguments.timeout
        )
        pause_settings = PauseSettings(
            silence_threshold_db=arguments.silence_threshold_db,
            minimum_pause_duration_ms=arguments.minimum_pause_duration_ms,
            shortening_policy_version=arguments.policy_version,
            minimum_pause_to_shorten_ms=arguments.minimum_pause_to_shorten_ms,
            target_remaining_pause_ms=arguments.target_remaining_pause_ms,
            maximum_removed_per_pause_ms=(
                arguments.maximum_removed_per_pause_ms
            ),
        )
        tools = ExecutableResolver(
            ffmpeg_path=arguments.ffmpeg,
            ffprobe_path=arguments.ffprobe,
            bundled_tools_directory=arguments.bundled_tools_directory,
        ).resolve_all()
        runner = SubprocessRunner()
        probe = FfprobeAdapter(
            runner=runner,
            ffprobe_path=tools.ffprobe,
            settings=audio_settings,
        )
        audio = probe.probe(arguments.input_file)
        detector = FfmpegPauseDetector(
            runner=runner,
            ffmpeg_path=tools.ffmpeg,
            subprocess_timeout_seconds=audio_settings.subprocess_timeout_seconds,
        )
        pauses = detector.detect(audio, settings=pause_settings)
        policy = PauseShorteningPolicy(pause_settings)
        service = PauseRemovalService(
            policy=policy,
            builder=EditMapBuilder(),
            renderer=FfmpegWavRenderer(
                runner=runner,
                probe=probe,
                ffmpeg_path=tools.ffmpeg,
                settings=audio_settings,
            ),
        )
        work_directory = arguments.work_directory.expanduser().resolve()
        result = service.remove(
            audio,
            pauses,
            destination=work_directory / "cleaned_audio.wav",
        )
        edit_map_path = work_directory / "edit_map.json"
        write_edit_map_atomic(result.edit_map, edit_map_path)
    except ProjectError as exc:
        logger.error("pause removal failed code=%s", exc.code)
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2

    shortened_count = sum(
        span.kind is EditKind.REMOVE for span in result.edit_map.spans
    )
    print(
        json.dumps(
            {
                "cleaned_audio": str(result.cleaned_audio_path),
                "edit_map": str(edit_map_path),
                "source_total_samples": result.edit_map.source_total_samples,
                "target_total_samples": result.edit_map.output_total_samples,
                "removed_samples": result.edit_map.removed_samples,
                "detected_pause_count": len(pauses),
                "shortened_pause_count": shortened_count,
                "policy_version": result.edit_map.policy_version,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _decimal_argument(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be a decimal number") from exc
    if not result.is_finite():
        raise argparse.ArgumentTypeError("must be finite")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
