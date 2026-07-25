"""Developer-only CLI for probing and canonicalizing one local audio file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.audio import (
    CanonicalWavConverter,
    ExecutableResolver,
    FfprobeAdapter,
    LocalAudioLoader,
    SubprocessRunner,
)
from larp_audio_mvp.audio.serialization import audio_load_result_to_dict
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import configure_logging, get_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect local audio and create a mono 48 kHz PCM s16le canonical WAV."
        )
    )
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--work-directory", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, default=None)
    parser.add_argument("--ffprobe", type=Path, default=None)
    parser.add_argument("--bundled-tools-directory", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    configure_logging()
    logger = get_logger("app.audio_inspect")

    try:
        settings = AudioSettings(subprocess_timeout_seconds=arguments.timeout)
        tools = ExecutableResolver(
            ffmpeg_path=arguments.ffmpeg,
            ffprobe_path=arguments.ffprobe,
            bundled_tools_directory=arguments.bundled_tools_directory,
        ).resolve_all()
        runner = SubprocessRunner()
        probe = FfprobeAdapter(
            runner=runner,
            ffprobe_path=tools.ffprobe,
            settings=settings,
        )
        converter = CanonicalWavConverter(
            runner=runner,
            probe=probe,
            ffmpeg_path=tools.ffmpeg,
            settings=settings,
        )
        result = LocalAudioLoader(
            probe=probe,
            converter=converter,
            work_directory=arguments.work_directory,
        ).load(arguments.input_file)
    except ProjectError as exc:
        logger.error("audio inspection failed code=%s", exc.code)
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            audio_load_result_to_dict(result),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

