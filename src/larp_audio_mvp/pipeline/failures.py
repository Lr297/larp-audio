"""Structured primary/secondary pipeline failure context."""

from __future__ import annotations

from larp_audio_mvp.core.errors import (
    PipelineCancellationError,
    PipelineError,
    ProjectError,
)

from .contracts import PipelineCleanupOutcome, PipelineStage, PipelineStageResult


class PipelineRunFailure(PipelineError):
    """Preserve the primary error while carrying factual cleanup diagnostics."""

    def __init__(
        self,
        primary_error: Exception,
        *,
        failed_stage: PipelineStage,
        cleanup_outcome: PipelineCleanupOutcome,
        stage_results: tuple[PipelineStageResult, ...] = (),
    ) -> None:
        primary_code = (
            primary_error.code
            if isinstance(primary_error, ProjectError)
            else "PIPELINE_STAGE_FAILED"
        )
        super().__init__(str(primary_error), code=primary_code)
        self.primary_error = primary_error
        self.failed_stage = failed_stage
        self.cleanup_outcome = cleanup_outcome
        self.secondary_error_code = cleanup_outcome.error_code
        self.stage_results = stage_results


class PipelineCancelledFailure(PipelineCancellationError):
    """Cancellation result with the same structured cleanup contract."""

    def __init__(
        self,
        primary_error: PipelineCancellationError,
        *,
        failed_stage: PipelineStage,
        cleanup_outcome: PipelineCleanupOutcome,
        stage_results: tuple[PipelineStageResult, ...] = (),
    ) -> None:
        super().__init__(str(primary_error), code=primary_error.code)
        self.primary_error = primary_error
        self.failed_stage = failed_stage
        self.cleanup_outcome = cleanup_outcome
        self.secondary_error_code = cleanup_outcome.error_code
        self.stage_results = stage_results


def contextualize_failure(
    primary_error: Exception,
    *,
    failed_stage: PipelineStage,
    cleanup_outcome: PipelineCleanupOutcome,
    stage_results: tuple[PipelineStageResult, ...] = (),
) -> PipelineRunFailure | PipelineCancelledFailure:
    if isinstance(primary_error, PipelineCancellationError):
        return PipelineCancelledFailure(
            primary_error,
            failed_stage=failed_stage,
            cleanup_outcome=cleanup_outcome,
            stage_results=stage_results,
        )
    return PipelineRunFailure(
        primary_error,
        failed_stage=failed_stage,
        cleanup_outcome=cleanup_outcome,
        stage_results=stage_results,
    )
