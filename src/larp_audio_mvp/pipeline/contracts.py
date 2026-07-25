"""Immutable public contracts for the complete local processing workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Any

from larp_audio_mvp.config import (
    AlignmentSettings,
    AudioSettings,
    ModelSettings,
    PauseSettings,
    SubtitleSettings,
)
from larp_audio_mvp.core.contracts import SubtitleDocument


class ScriptSourceKind(StrEnum):
    PASTED = "pasted"
    TYPED = "typed"
    LOADED_FILE = "loaded_file"
    CLI_FILE = "cli_file"
    STDIN = "stdin"


class NewlineStyle(StrEnum):
    NONE = "none"
    LF = "lf"
    CRLF = "crlf"
    CR = "cr"
    UNICODE = "unicode"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class ScriptInput:
    exact_text: str
    source_kind: ScriptSourceKind
    source_path: Path | None
    encoding: str
    newline_style: NewlineStyle
    character_count: int
    visible_character_count: int
    script_word_count: int
    sha256: str
    was_edited_in_gui: bool
    has_bom: bool = False


@dataclass(frozen=True, slots=True)
class PublishedSourceReference:
    """Portable source identity that is safe to persist in public artifacts."""

    display_name: str
    logical_role: str
    content_sha256: str
    source_kind: str
    original_extension: str
    had_bom: bool | None = None
    newline_style: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineCleanupOutcome:
    attempted: bool
    completed: bool
    staging_path_safe_display: str | None
    residual_workspace_exists: bool
    error_code: str | None = None
    message: str = "Cleanup status is unknown."
    warnings: tuple[str, ...] = ()
    manual_cleanup_may_be_required: bool = False
    residual_workspace_path: Path | None = field(default=None, repr=False, compare=False)


class PipelineStage(StrEnum):
    PREFLIGHT = "preflight"
    PREPARING_WORKSPACE = "preparing_workspace"
    ANALYZING_AUDIO = "analyzing_audio"
    CANONICALIZING_AUDIO = "canonicalizing_audio"
    DETECTING_PAUSES = "detecting_pauses"
    SHORTENING_PAUSES = "shortening_pauses"
    RENDERING_CLEANED_AUDIO = "rendering_cleaned_audio"
    RECOGNIZING_SPEECH = "recognizing_speech"
    ALIGNING_SCRIPT = "aligning_script"
    GENERATING_SUBTITLES = "generating_subtitles"
    VALIDATING_ARTIFACTS = "validating_artifacts"
    WRITING_REPORTS = "writing_reports"
    CREATING_PACKAGE = "creating_package"
    PUBLISHING_RESULTS = "publishing_results"
    COMPLETE = "complete"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"


EXECUTION_STAGES = (
    PipelineStage.PREFLIGHT,
    PipelineStage.PREPARING_WORKSPACE,
    PipelineStage.ANALYZING_AUDIO,
    PipelineStage.CANONICALIZING_AUDIO,
    PipelineStage.DETECTING_PAUSES,
    PipelineStage.SHORTENING_PAUSES,
    PipelineStage.RENDERING_CLEANED_AUDIO,
    PipelineStage.RECOGNIZING_SPEECH,
    PipelineStage.ALIGNING_SCRIPT,
    PipelineStage.GENERATING_SUBTITLES,
    PipelineStage.VALIDATING_ARTIFACTS,
    PipelineStage.WRITING_REPORTS,
    PipelineStage.CREATING_PACKAGE,
    PipelineStage.PUBLISHING_RESULTS,
)


@dataclass(frozen=True, slots=True)
class PipelineProgress:
    stage: PipelineStage
    stage_index: int
    total_stages: int
    message: str
    detail: str = ""
    indeterminate: bool = True
    cancel_requested: bool = False
    completed_stage_count: int = 0


@dataclass(frozen=True, slots=True)
class PipelineStageResult:
    stage: PipelineStage
    status: str
    started_at: str
    completed_at: str
    elapsed_milliseconds: int
    warnings: tuple[str, ...] = ()
    artifact_names: tuple[str, ...] = ()
    metrics: tuple[tuple[str, Any], ...] = ()
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineConfigurationSnapshot:
    values: tuple[tuple[str, str], ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class PipelineRunRequest:
    source_audio_path: Path
    script_input: ScriptInput
    local_model_path: Path
    output_parent_directory: Path
    audio_settings: AudioSettings
    pause_settings: PauseSettings
    recognition_settings: ModelSettings
    alignment_settings: AlignmentSettings
    subtitle_settings: SubtitleSettings
    application_version: str
    max_script_characters: int = 500_000
    output_run_name: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineArtifact:
    relative_path: str
    role: str
    media_type: str
    size_bytes: int
    sha256: str
    schema_version: str | None = None
    required: bool = True
    timeline: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    source_duration_samples: int
    cleaned_duration_samples: int
    removed_samples: int
    sample_rate: int
    detected_pause_count: int
    shortened_pause_count: int
    subtitle_block_count: int
    unresolved_word_count: int
    interpolated_word_count: int
    text_coverage: Fraction
    timing_coverage: Fraction
    maximum_characters_per_second: Fraction
    package_size_bytes: int


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    run_id: str
    final_output_directory: Path
    cleaned_audio_path: Path
    edit_map_path: Path
    recognition_path: Path
    alignment_path: Path
    subtitle_blocks_path: Path
    srt_path: Path
    processing_report_path: Path
    manifest_path: Path
    package_zip_path: Path
    warnings: tuple[str, ...]
    stage_results: tuple[PipelineStageResult, ...]
    summary: PipelineSummary
    subtitle_document: SubtitleDocument
    cancelled: bool = False
    completed_successfully: bool = True
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    schema_version: str
    run_id: str
    application_version: str
    processing_started_at: str
    report_generated_at: str
    processing_elapsed_milliseconds: int
    platform: str
    python_version: str
    source_audio_filename: str
    source_audio_sha256: str
    source_audio_size_bytes: int
    script_sha256: str
    script_character_count: int
    script_word_count: int
    configuration: PipelineConfigurationSnapshot
    stage_results: tuple[PipelineStageResult, ...]
    warnings: tuple[str, ...]
    artifact_names: tuple[str, ...]
    success: bool
    metrics: tuple[tuple[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    schema_version: str
    run_id: str
    application_version: str
    created_at: str
    source_audio_sha256: str
    script_sha256: str
    configuration_sha256: str
    artifacts: tuple[PipelineArtifact, ...]
    total_artifact_count: int
    total_artifact_bytes: int
    manifest_filename: str
    package_filename: str
