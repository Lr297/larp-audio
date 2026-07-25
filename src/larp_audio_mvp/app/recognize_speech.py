"""Developer CLI for local word-timestamp recognition on cleaned audio."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.audio import read_canonical_wav
from larp_audio_mvp.audio.serialization import read_edit_map
from larp_audio_mvp.config import AudioSettings, ModelSettings
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import configure_logging, get_logger
from larp_audio_mvp.models import (
    FasterWhisperInference,
    LocalSpeechRecognizer,
    LocalWhisperModelManager,
    write_recognition_atomic,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run local Faster-Whisper on cleaned WAV and write word timing evidence."
        )
    )
    parser.add_argument("cleaned_wav", type=Path)
    parser.add_argument("edit_map", type=Path)
    parser.add_argument("--work-directory", type=Path, required=True)
    parser.add_argument("--model", choices=("tiny", "base", "small"), required=True)
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--model-root", type=Path, default=Path("models"))
    parser.add_argument("--backend", default="faster-whisper")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default=None)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--temperature", type=_decimal_argument, default=Decimal("0"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    configure_logging()
    logger = get_logger("app.recognize_speech")
    try:
        settings = ModelSettings(
            model_path=(
                None
                if arguments.model_path is None
                else arguments.model_path.expanduser().resolve()
            ),
            whisper_backend=arguments.backend,
            whisper_model=arguments.model,
            device=arguments.device,
            compute_type=arguments.compute_type,
            language=arguments.language,
            beam_size=arguments.beam_size,
            temperature=arguments.temperature,
        )
        cleaned_audio = read_canonical_wav(arguments.cleaned_wav, AudioSettings())
        edit_map = read_edit_map(arguments.edit_map)
        recognizer = LocalSpeechRecognizer(
            model_manager=LocalWhisperModelManager(
                model_root=arguments.model_root
            ),
            backend=FasterWhisperInference(),
        )
        result = recognizer.recognize(
            cleaned_audio,
            edit_map,
            settings=settings,
        )
        output_path = (
            arguments.work_directory.expanduser().resolve() / "recognition.json"
        )
        write_recognition_atomic(result, output_path)
    except ProjectError as exc:
        logger.error("speech recognition failed code=%s", exc.code)
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "recognition": str(output_path),
                "backend": result.backend,
                "model": result.model,
                "language": result.language,
                "word_count": len(result.words),
                "sample_rate": result.sample_rate,
                "cleaned_total_samples": result.duration_samples_cleaned,
                "original_total_samples": result.duration_samples_original,
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
