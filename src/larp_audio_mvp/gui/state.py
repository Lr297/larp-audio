"""Immutable GUI state, recoverable failures, and state invariants."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from pathlib import Path

from larp_audio_mvp.core.contracts import AlignmentResult, AudioInfo, SubtitleDocument
from larp_audio_mvp.core.errors import ConfigurationError
from larp_audio_mvp.subtitles.service import SubtitleGenerationSummary
from larp_audio_mvp.pipeline.contracts import PipelineCleanupOutcome, PipelineProgress, PipelineRunResult, ScriptInput


class GuiPhase(StrEnum):
    EMPTY = "empty"
    INPUT_READY = "input_ready"
    PREFLIGHTING = "preflighting"
    LOADING_ALIGNMENT = "loading_alignment"
    READY = "ready"
    PROCESSING = "processing"
    FINISHING = "finishing"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCESS = "success"
    ERROR = "error"  # Legacy value: recoverable failures no longer replace workflow phase.


class FailureSource(StrEnum):
    ALIGNMENT_LOADING = "alignment_loading"
    SUBTITLE_GENERATION = "subtitle_generation"
    FULL_PIPELINE = "full_pipeline"
    SETTINGS_VALIDATION = "settings_validation"
    DRAG_AND_DROP = "drag_and_drop"
    DESKTOP_ACTION = "desktop_action"
    DIALOG_ACTION = "dialog_action"
    PREVIEW = "preview"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class AlignmentSummary:
    script_word_count: int
    asr_word_count: int
    matched_word_count: int
    interpolated_word_count: int
    unresolved_word_count: int
    text_alignment_coverage: Fraction
    timing_coverage: Fraction
    sample_rate: int
    cleaned_duration_samples: int
    provenance_complete: bool
    schema_version: str
    warnings_count: int


@dataclass(frozen=True, slots=True)
class GeneratedResult:
    summary: SubtitleGenerationSummary
    document: SubtitleDocument


@dataclass(frozen=True, slots=True)
class AudioPreflightRequest:
    request_id: str
    source_path: Path
    normalized_path_identity: str
    sequence_number: int
    source_size_bytes: int | None = None
    source_mtime_ns: int | None = None


@dataclass(frozen=True, slots=True)
class AudioPreflightResult:
    request_id: str
    source_path: Path
    normalized_path_identity: str
    metadata: AudioInfo | None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.metadata is not None and self.error_code is None


@dataclass(frozen=True, slots=True)
class GuiFailure:
    title: str
    message: str
    error_code: str
    details: str = ""
    related_path: Path | None = None
    is_unexpected: bool = False
    recoverable: bool = True
    source: FailureSource = FailureSource.INTERNAL
    cleanup_outcome: PipelineCleanupOutcome | None = None

    @property
    def code(self) -> str:
        """Compatibility accessor retained for Stage 10 callers."""
        return self.error_code

    @property
    def path(self) -> Path | None:
        """Compatibility accessor retained for Stage 10 callers."""
        return self.related_path


def format_failure_details(failure: GuiFailure) -> str:
    """Return the deterministic, privacy-bounded text copied on explicit request."""
    lines = [
            f"Title: {failure.title}",
            f"Code: {failure.error_code}",
            f"Message: {failure.message}",
            f"Path: {failure.related_path if failure.related_path is not None else '—'}",
            f"Details: {failure.details or '—'}",
            f"Source: {failure.source.value}",
            f"Recoverable: {'yes' if failure.recoverable else 'no'}",
            f"Unexpected: {'yes' if failure.is_unexpected else 'no'}",
    ]
    if failure.cleanup_outcome is not None:
        cleanup = failure.cleanup_outcome
        lines.extend((
            f"Cleanup attempted: {'yes' if cleanup.attempted else 'no'}",
            f"Cleanup completed: {'yes' if cleanup.completed else 'no'}",
            f"Residual workspace: {'yes' if cleanup.residual_workspace_exists else 'no'}",
            f"Cleanup code: {cleanup.error_code or '—'}",
            f"Cleanup message: {cleanup.message}",
        ))
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class GuiState:
    phase: GuiPhase = GuiPhase.EMPTY
    alignment_path: Path | None = None
    output_directory: Path | None = None
    alignment: AlignmentResult | None = None
    alignment_summary: AlignmentSummary | None = None
    generated_result: GeneratedResult | None = None
    source_audio_path: Path | None = None
    audio_preflight_request: AudioPreflightRequest | None = None
    audio_preflight_metadata: AudioInfo | None = None
    audio_preflight_ready: bool | None = None
    script_input: ScriptInput | None = None
    local_model_path: Path | None = None
    pipeline_result: PipelineRunResult | None = None
    pipeline_progress: PipelineProgress | None = None
    completed_pipeline_stages: tuple[str, ...] = field(default_factory=tuple)
    progress_message: str = "Select an existing alignment.json to begin."
    active_failure: GuiFailure | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    task_active: bool = False

    @property
    def processing(self) -> bool:
        return self.task_active

    @property
    def failure(self) -> GuiFailure | None:
        """Deprecated read-only alias; active_failure is canonical."""
        return self.active_failure


def validate_gui_state(state: GuiState) -> None:
    """Reject workflow combinations that the view cannot render truthfully."""
    if state.phase is GuiPhase.EMPTY:
        valid = state.alignment is None and state.generated_result is None and state.pipeline_result is None and not state.task_active
    elif state.phase is GuiPhase.INPUT_READY:
        valid = (
            state.source_audio_path is not None
            and state.script_input is not None
            and state.local_model_path is not None
            and state.output_directory is not None
            and not state.task_active
        )
    elif state.phase is GuiPhase.LOADING_ALIGNMENT:
        valid = not state.task_active
    elif state.phase is GuiPhase.READY:
        valid = state.alignment is not None and not state.task_active
    elif state.phase is GuiPhase.PREFLIGHTING:
        valid = (
            (state.alignment is not None or state.source_audio_path is not None)
            and (state.task_active or state.audio_preflight_request is not None)
        )
    elif state.phase in (GuiPhase.PROCESSING, GuiPhase.FINISHING, GuiPhase.CANCELLING):
        valid = (state.alignment is not None or state.source_audio_path is not None) and state.task_active
    elif state.phase is GuiPhase.CANCELLED:
        valid = not state.task_active
    elif state.phase is GuiPhase.SUCCESS:
        valid = (
            (state.alignment is not None or state.pipeline_result is not None)
            and (state.generated_result is not None or state.pipeline_result is not None)
            and not state.task_active
        )
    else:
        valid = False
    if state.alignment_summary is not None and state.alignment is None:
        valid = False
    if not valid:
        raise ConfigurationError(
            f"Invalid GUI state for phase {state.phase.value}", code="GUI_STATE_INVALID"
        )


def summarize_alignment(alignment: AlignmentResult) -> AlignmentSummary:
    diagnostics = alignment.diagnostics
    matched = (
        diagnostics.exact_matches
        + diagnostics.normalized_matches
        + diagnostics.fuzzy_matches
        + diagnostics.split_merge_matches
    )
    return AlignmentSummary(
        script_word_count=diagnostics.total_script_words,
        asr_word_count=diagnostics.total_asr_words,
        matched_word_count=matched,
        interpolated_word_count=diagnostics.interpolated_words,
        unresolved_word_count=diagnostics.unresolved_script_words,
        text_alignment_coverage=diagnostics.text_alignment_coverage,
        timing_coverage=diagnostics.total_timing_coverage,
        sample_rate=alignment.sample_rate,
        cleaned_duration_samples=alignment.edit_map.output_total_samples,
        provenance_complete=diagnostics.provenance_complete,
        schema_version=alignment.schema_version,
        warnings_count=len(alignment.warnings),
    )
