"""Developer CLI for Stage 9 subtitle JSON and cleaned-timeline SRT."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Sequence

from larp_audio_mvp.config import SubtitleSettings, load_config
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import configure_logging
from larp_audio_mvp.subtitles.service import SubtitleGenerationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate script-preserving subtitle_blocks.json and cleaned-timeline SRT."
        )
    )
    parser.add_argument("--alignment", required=True, type=Path)
    parser.add_argument("--blocks-output", required=True, type=Path)
    parser.add_argument("--srt-output", required=True, type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional project TOML; only validated [subtitles] settings are used.",
    )
    return parser


def _decimal(value: Fraction) -> str:
    with localcontext() as context:
        context.prec = 28
        return format(
            Decimal(value.numerator) / Decimal(value.denominator), "f"
        )


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    arguments = _parser().parse_args(argv)
    try:
        settings = (
            load_config(arguments.config).subtitles
            if arguments.config is not None
            else SubtitleSettings()
        )
        summary = SubtitleGenerationService().generate(
            alignment_path=arguments.alignment,
            blocks_output=arguments.blocks_output,
            srt_output=arguments.srt_output,
            settings=settings,
        )
        print(
            json.dumps(
                {
                    "subtitle_blocks_path": str(summary.subtitle_blocks_path),
                    "srt_path": str(summary.srt_path),
                    "schema_version": summary.schema_version,
                    "block_count": summary.block_count,
                    "script_word_count": summary.script_word_count,
                    "exported_word_count": summary.exported_word_count,
                    "unresolved_word_count": summary.unresolved_word_count,
                    "interpolated_word_count": summary.interpolated_word_count,
                    "text_coverage": _decimal(summary.text_coverage),
                    "timing_coverage": _decimal(summary.timing_coverage),
                    "maximum_characters_per_second": _decimal(
                        summary.maximum_characters_per_second
                    ),
                    "single_word_blocks": summary.single_word_blocks,
                    "short_blocks": summary.short_blocks,
                    "average_words_per_block": _decimal(
                        summary.average_words_per_block
                    ),
                    "output_paths_validated": summary.output_paths_validated,
                    "existing_outputs_replaced": summary.existing_outputs_replaced,
                    "rollback_performed": summary.rollback_performed,
                    "warnings_count": summary.warnings_count,
                    "srt_exportable": summary.srt_exportable,
                    "segmentation_policy_version": (
                        summary.segmentation_policy_version
                    ),
                    "candidate_evaluations": summary.candidate_evaluations,
                    "syntax_analyzer_mode": summary.syntax_analyzer_mode,
                    "candidate_boundary_count": summary.candidate_boundary_count,
                    "legal_boundary_count": summary.legal_boundary_count,
                    "discouraged_boundary_count": summary.discouraged_boundary_count,
                    "forbidden_boundary_count": summary.forbidden_boundary_count,
                    "forced_syntax_split_count": summary.forced_syntax_split_count,
                    "phase_timings_milliseconds": dict(
                        summary.phase_timings_milliseconds
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    except ProjectError as exc:
        print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
