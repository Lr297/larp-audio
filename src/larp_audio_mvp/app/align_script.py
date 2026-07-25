"""Developer CLI for deterministic script-to-ASR word timing alignment."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.alignment import align_files, write_alignment_atomic
from larp_audio_mvp.config import AlignmentSettings, load_config
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import configure_logging, get_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Align exact UTF-8 script words to existing recognition timing evidence."
        )
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--recognition", type=Path, required=True)
    parser.add_argument("--edit-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional project TOML; only its [alignment] section is used.",
    )
    parser.add_argument("--fuzzy-threshold", type=_decimal_argument, default=None)
    parser.add_argument("--max-dp-cells", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    configure_logging()
    logger = get_logger("app.align_script")
    try:
        settings = (
            AlignmentSettings()
            if arguments.config is None
            else load_config(arguments.config).alignment
        )
        if arguments.fuzzy_threshold is not None or arguments.max_dp_cells is not None:
            settings = AlignmentSettings(
                fuzzy_threshold=(
                    settings.fuzzy_threshold
                    if arguments.fuzzy_threshold is None
                    else arguments.fuzzy_threshold
                ),
                min_fuzzy_token_length=settings.min_fuzzy_token_length,
                max_dp_cells=(
                    settings.max_dp_cells
                    if arguments.max_dp_cells is None
                    else arguments.max_dp_cells
                ),
                max_interpolation_words=settings.max_interpolation_words,
                max_interpolation_gap_ms=settings.max_interpolation_gap_ms,
                minimum_coverage_warning=settings.minimum_coverage_warning,
                enable_split_merge=settings.enable_split_merge,
                enable_fuzzy_matching=settings.enable_fuzzy_matching,
            )
        result = align_files(
            script_path=arguments.script,
            recognition_path=arguments.recognition,
            edit_map_path=arguments.edit_map,
            settings=settings,
        )
        output_path = arguments.output.expanduser().resolve()
        write_alignment_atomic(result, output_path)
    except ProjectError as exc:
        logger.error("script alignment failed code=%s", exc.code)
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2

    diagnostics = result.diagnostics
    matched_words = (
        diagnostics.exact_matches
        + diagnostics.normalized_matches
        + diagnostics.fuzzy_matches
        + sum(
            word.match_type.value
            in ("one_script_to_many_asr", "many_script_to_one_asr")
            for word in result.aligned_words
        )
    )
    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "script_words": diagnostics.total_script_words,
                "asr_words": diagnostics.total_asr_words,
                "total_asr_words": diagnostics.total_asr_words,
                "classified_asr_words": diagnostics.classified_asr_words,
                "rejected_asr_evidence_count": (
                    diagnostics.rejected_asr_evidence_count
                ),
                "provenance_complete": diagnostics.provenance_complete,
                "schema_version": result.schema_version,
                "matched_words": matched_words,
                "interpolated_words": diagnostics.interpolated_words,
                "unresolved_words": diagnostics.unresolved_script_words,
                "text_alignment_coverage": _decimal(diagnostics.text_alignment_coverage),
                "timing_coverage": _decimal(diagnostics.total_timing_coverage),
                "warnings_count": len(result.warnings),
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


def _decimal(value: Fraction) -> str:
    with localcontext() as context:
        context.prec = 12
        return str(Decimal(value.numerator) / Decimal(value.denominator))


if __name__ == "__main__":
    raise SystemExit(main())
