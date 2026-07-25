"""Path-safe orchestration and best-effort two-artifact publication."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns

from larp_audio_mvp.alignment import read_alignment
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.errors import (
    ProjectError,
    SubtitleCoverageError,
    SubtitleOutputPathError,
    SubtitleOutputPreparationError,
    SubtitlePublicationError,
    SubtitleRollbackError,
)
from larp_audio_mvp.exports.srt import SrtExporter, validate_srt
from larp_audio_mvp.subtitles.chunker import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.paths import SubtitlePathPlan
from larp_audio_mvp.subtitles.policy import SEMANTIC_SUBTITLE_POLICY_VERSION
from larp_audio_mvp.subtitles.serialization import (
    read_subtitle_document,
    render_subtitle_document_json,
)


@dataclass(frozen=True, slots=True)
class SubtitleGenerationSummary:
    subtitle_blocks_path: Path
    srt_path: Path
    schema_version: str
    block_count: int
    script_word_count: int
    exported_word_count: int
    unresolved_word_count: int
    interpolated_word_count: int
    text_coverage: Fraction
    timing_coverage: Fraction
    maximum_characters_per_second: Fraction
    single_word_blocks: int
    short_blocks: int
    average_words_per_block: Fraction
    output_paths_validated: bool
    existing_outputs_replaced: bool
    rollback_performed: bool
    warnings_count: int
    srt_exportable: bool
    segmentation_policy_version: str = SEMANTIC_SUBTITLE_POLICY_VERSION
    candidate_evaluations: int = 0
    phase_timings_milliseconds: tuple[tuple[str, str], ...] = ()
    syntax_analyzer_mode: str = ""
    candidate_boundary_count: int = 0
    legal_boundary_count: int = 0
    discouraged_boundary_count: int = 0
    forbidden_boundary_count: int = 0
    forced_syntax_split_count: int = 0


class SubtitleGenerationService:
    """Validate every path before mutation, then publish a verified pair."""

    def __init__(
        self,
        *,
        chunker: DeterministicSubtitleChunker | None = None,
        exporter: SrtExporter | None = None,
    ) -> None:
        self._chunker = chunker or DeterministicSubtitleChunker()
        self._exporter = exporter or SrtExporter()

    def generate(
        self,
        *,
        alignment_path: Path,
        blocks_output: Path,
        srt_output: Path,
        settings: SubtitleSettings,
    ) -> SubtitleGenerationSummary:
        total_started = perf_counter_ns()
        phase_ns: dict[str, int] = {}
        plan = SubtitlePathPlan.build(
            alignment_path=alignment_path,
            subtitle_blocks_path=blocks_output,
            srt_path=srt_output,
        )
        alignment_started = perf_counter_ns()
        try:
            alignment_bytes = plan.alignment_path.read_bytes()
        except (OSError, UnicodeError) as exc:
            raise SubtitleOutputPathError(
                f"cannot read alignment input: {plan.alignment_path}",
                code="SUBTITLE_ALIGNMENT_INPUT_READ_FAILED",
            ) from exc
        alignment = read_alignment(plan.alignment_path)
        phase_ns["alignment_read"] = perf_counter_ns() - alignment_started
        plan.prepare_directories()
        prior_blocks, prior_srt = plan.read_existing_outputs()

        document, chunk_metrics = self._chunker.chunk_with_metrics(
            alignment,
            settings=settings,
            source_alignment_sha256=hashlib.sha256(alignment_bytes).hexdigest(),
        )
        phase_ns["tokenization"] = chunk_metrics.tokenization_nanoseconds
        phase_ns["candidate_boundary_detection"] = (
            chunk_metrics.candidate_boundary_detection_nanoseconds
        )
        phase_ns["syntax_parser_initialization"] = (
            chunk_metrics.parser_initialization_nanoseconds
        )
        phase_ns["syntax_parse"] = chunk_metrics.syntax_parse_nanoseconds
        phase_ns["segmentation"] = chunk_metrics.segmentation_nanoseconds
        phase_ns["orphan_repair"] = chunk_metrics.orphan_repair_nanoseconds
        phase_ns["line_layout"] = chunk_metrics.line_layout_nanoseconds
        phase_ns["applying_word_timings"] = (
            chunk_metrics.timing_application_nanoseconds
        )
        phase_ns["block_construction"] = (
            chunk_metrics.block_construction_nanoseconds
        )
        phase_ns["validation"] = chunk_metrics.validation_nanoseconds
        if not document.diagnostics.srt_exportable:
            raise SubtitleCoverageError(
                "subtitle timing coverage is below the configured export threshold",
                code="SUBTITLE_TIMING_COVERAGE_TOO_LOW",
            )
        json_started = perf_counter_ns()
        json_payload = render_subtitle_document_json(document)
        phase_ns["json_serialization"] = perf_counter_ns() - json_started
        srt_started = perf_counter_ns()
        srt_payload = self._exporter.render(document)
        validate_srt(srt_payload, document)
        phase_ns["srt_render_validation"] = perf_counter_ns() - srt_started

        published_blocks = False
        published_srt = False
        operation_error: Exception | None = None
        try:
            publication_started = perf_counter_ns()
            self._write_staging(
                plan.subtitle_blocks_partial_path,
                json_payload,
                role="subtitle_blocks staging",
            )
            reread_started = perf_counter_ns()
            verified = read_subtitle_document(plan.subtitle_blocks_partial_path)
            phase_ns["json_reread_validation"] = (
                perf_counter_ns() - reread_started
            )
            self._write_staging(
                plan.srt_partial_path,
                srt_payload,
                role="SRT staging",
            )
            validate_srt(plan.srt_partial_path.read_bytes(), verified)
            os.replace(
                plan.subtitle_blocks_partial_path, plan.subtitle_blocks_path
            )
            published_blocks = True
            os.replace(plan.srt_partial_path, plan.srt_path)
            published_srt = True
            phase_ns["publication"] = perf_counter_ns() - publication_started
            reread_started = perf_counter_ns()
            final_document = read_subtitle_document(plan.subtitle_blocks_path)
            validate_srt(plan.srt_path.read_bytes(), final_document)
            phase_ns["json_reread_validation"] += (
                perf_counter_ns() - reread_started
            )
        except Exception as exc:
            operation_error = exc
            if published_blocks or published_srt:
                rollback_errors = self._rollback(
                    plan,
                    prior_blocks=prior_blocks,
                    prior_srt=prior_srt,
                    restore_blocks=published_blocks,
                    restore_srt=published_srt,
                )
                if rollback_errors:
                    raise SubtitleRollbackError(
                        "subtitle publication failed and rollback was incomplete: "
                        + "; ".join(rollback_errors),
                        code="SUBTITLE_ROLLBACK_FAILED",
                    ) from exc
            if isinstance(exc, ProjectError):
                raise
            raise SubtitlePublicationError(
                "subtitle artifact publication failed",
                code="SUBTITLE_PUBLICATION_FAILED",
            ) from exc
        finally:
            cleanup_errors = self._cleanup_paths(
                plan.subtitle_blocks_partial_path,
                plan.srt_partial_path,
            )
            if cleanup_errors and operation_error is None:
                raise SubtitleOutputPreparationError(
                    "cannot clean subtitle staging files: "
                    + "; ".join(cleanup_errors),
                    code="SUBTITLE_STAGING_CLEANUP_FAILED",
                )

        diagnostics = document.diagnostics
        phase_ns["total"] = perf_counter_ns() - total_started
        return SubtitleGenerationSummary(
            subtitle_blocks_path=plan.subtitle_blocks_path,
            srt_path=plan.srt_path,
            schema_version=document.schema_version,
            block_count=diagnostics.total_blocks,
            script_word_count=diagnostics.total_script_words,
            exported_word_count=diagnostics.exported_script_words,
            unresolved_word_count=diagnostics.unresolved_script_words,
            interpolated_word_count=diagnostics.interpolated_script_words,
            text_coverage=diagnostics.text_coverage,
            timing_coverage=diagnostics.timing_coverage,
            maximum_characters_per_second=(
                diagnostics.maximum_characters_per_second
            ),
            single_word_blocks=diagnostics.single_word_blocks,
            short_blocks=diagnostics.short_blocks,
            average_words_per_block=diagnostics.average_words_per_block,
            output_paths_validated=True,
            existing_outputs_replaced=(
                prior_blocks is not None or prior_srt is not None
            ),
            rollback_performed=False,
            warnings_count=diagnostics.warnings_count,
            srt_exportable=diagnostics.srt_exportable,
            segmentation_policy_version=SEMANTIC_SUBTITLE_POLICY_VERSION,
            candidate_evaluations=chunk_metrics.candidate_evaluations,
            syntax_analyzer_mode=chunk_metrics.syntax_analyzer_mode,
            candidate_boundary_count=chunk_metrics.candidate_boundary_count,
            legal_boundary_count=chunk_metrics.legal_boundary_count,
            discouraged_boundary_count=chunk_metrics.discouraged_boundary_count,
            forbidden_boundary_count=chunk_metrics.forbidden_boundary_count,
            forced_syntax_split_count=chunk_metrics.forced_syntax_split_count,
            phase_timings_milliseconds=tuple(
                (name, _milliseconds(value))
                for name, value in phase_ns.items()
            ),
        )

    @staticmethod
    def _write_staging(path: Path, payload: bytes, *, role: str) -> None:
        try:
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise SubtitleOutputPreparationError(
                f"cannot write {role}: {path}",
                code="SUBTITLE_OUTPUT_PREPARATION_FAILED",
            ) from exc

    def _rollback(
        self,
        plan: SubtitlePathPlan,
        *,
        prior_blocks: bytes | None,
        prior_srt: bytes | None,
        restore_blocks: bool,
        restore_srt: bool,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if restore_blocks:
            failure = self._restore_one(
                final=plan.subtitle_blocks_path,
                rollback=plan.subtitle_blocks_rollback_path,
                prior=prior_blocks,
                role="subtitle_blocks output",
            )
            if failure:
                failures.append(failure)
        if restore_srt:
            failure = self._restore_one(
                final=plan.srt_path,
                rollback=plan.srt_rollback_path,
                prior=prior_srt,
                role="SRT output",
            )
            if failure:
                failures.append(failure)
        return tuple(failures)

    @staticmethod
    def _restore_one(
        *,
        final: Path,
        rollback: Path,
        prior: bytes | None,
        role: str,
    ) -> str | None:
        try:
            if prior is None:
                final.unlink(missing_ok=True)
                return None
            with rollback.open("xb") as stream:
                stream.write(prior)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(rollback, final)
            return None
        except OSError as exc:
            # A successfully written rollback file is intentionally retained as
            # recoverable evidence when replacement itself fails.
            return f"cannot restore {role}: {exc}"

    @staticmethod
    def _cleanup_paths(*paths: Path) -> tuple[str, ...]:
        failures: list[str] = []
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                failures.append(f"{path}: {exc}")
        return tuple(failures)


def _milliseconds(nanoseconds: int) -> str:
    return format(Decimal(nanoseconds) / Decimal(1_000_000), ".3f")
