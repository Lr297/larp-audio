"""Developer CLI for read-only silence detection in canonical WAV files."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.audio import (
    ExecutableResolver,
    FfmpegPauseDetector,
    SubprocessRunner,
    read_canonical_wav,
)
from larp_audio_mvp.audio.serialization import pause_detection_to_dict
from larp_audio_mvp.config import AudioSettings, PauseSettings
from larp_audio_mvp.core.contracts import AudioInfo
from larp_audio_mvp.core.errors import AudioProbeError, PauseDetectionError, ProjectError
from larp_audio_mvp.core.logging import configure_logging, get_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Detect silence intervals in a canonical mono 48 kHz PCM s16le WAV."
        )
    )
    parser.add_argument("input_file", type=Path)
    parser.add_argument(
        "--silence-threshold-db",
        type=_decimal_argument,
        required=True,
    )
    parser.add_argument(
        "--minimum-pause-duration-ms",
        type=int,
        required=True,
    )
    parser.add_argument("--ffmpeg", type=Path, default=None)
    parser.add_argument("--bundled-tools-directory", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    configure_logging()
    logger = get_logger("app.detect_pauses")

    try:
        audio_settings = AudioSettings(
            subprocess_timeout_seconds=arguments.timeout
        )
        pause_settings = PauseSettings(
            silence_threshold_db=arguments.silence_threshold_db,
            minimum_pause_duration_ms=arguments.minimum_pause_duration_ms,
        )
        ffmpeg = ExecutableResolver(
            ffmpeg_path=arguments.ffmpeg,
            bundled_tools_directory=arguments.bundled_tools_directory,
        ).resolve("ffmpeg")
        audio = _read_canonical_wav(arguments.input_file, audio_settings)
        detector = FfmpegPauseDetector(
            runner=SubprocessRunner(),
            ffmpeg_path=ffmpeg,
            subprocess_timeout_seconds=audio_settings.subprocess_timeout_seconds,
        )
        segments = detector.detect(audio, settings=pause_settings)
    except ProjectError as exc:
        logger.error("pause detection failed code=%s", exc.code)
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            pause_detection_to_dict(audio, pause_settings, segments),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _read_canonical_wav(path: Path, settings: AudioSettings) -> AudioInfo:
    try:
        return read_canonical_wav(path, settings)
    except AudioProbeError as exc:
        raise PauseDetectionError(
            str(exc),
            code=exc.code,
        ) from exc


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
