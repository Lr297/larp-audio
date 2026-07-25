"""Project-specific exceptions with stable machine-readable error codes."""

from __future__ import annotations


class ProjectError(Exception):
    """Base class for expected project failures."""

    default_code = "PROJECT_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.default_code


class AudioError(ProjectError):
    default_code = "AUDIO_ERROR"


class AudioProbeError(AudioError):
    default_code = "AUDIO_PROBE_ERROR"


class AudioConversionError(AudioError):
    default_code = "AUDIO_CONVERSION_ERROR"


class PauseDetectionError(AudioError):
    default_code = "PAUSE_DETECTION_ERROR"


class AudioRenderError(AudioError):
    default_code = "AUDIO_RENDER_ERROR"


class EditMapError(ProjectError):
    default_code = "EDIT_MAP_ERROR"


class TimelineMappingError(ProjectError):
    default_code = "TIMELINE_MAPPING_ERROR"


class ProcessExecutionError(AudioError):
    default_code = "PROCESS_FAILED"


class ProcessTimeoutError(AudioError):
    default_code = "PROCESS_TIMEOUT"


class SpeechRecognitionError(ProjectError):
    default_code = "STT_ERROR"


class SpeechModelError(SpeechRecognitionError):
    default_code = "STT_MODEL_ERROR"


class SpeechBackendError(SpeechRecognitionError):
    default_code = "STT_BACKEND_ERROR"


class RecognitionSerializationError(SpeechRecognitionError):
    default_code = "STT_SERIALIZATION_ERROR"


class AlignmentError(ProjectError):
    default_code = "ALIGNMENT_ERROR"


class ScriptReadError(AlignmentError):
    default_code = "SCRIPT_READ_ERROR"


class ScriptTokenizationError(AlignmentError):
    default_code = "SCRIPT_TOKENIZATION_ERROR"


class RecognitionCompatibilityError(AlignmentError):
    default_code = "RECOGNITION_COMPATIBILITY_ERROR"


class AlignmentLimitExceededError(AlignmentError):
    default_code = "ALIGNMENT_LIMIT_EXCEEDED"


class AlignmentSerializationError(AlignmentError):
    default_code = "ALIGNMENT_SERIALIZATION_ERROR"


class AlignmentValidationError(AlignmentError):
    default_code = "ALIGNMENT_VALIDATION_ERROR"


class SubtitleError(ProjectError):
    default_code = "SUBTITLE_ERROR"


class SubtitleChunkingError(SubtitleError):
    default_code = "SUBTITLE_CHUNKING_ERROR"


class SubtitleValidationError(SubtitleError):
    default_code = "SUBTITLE_VALIDATION_ERROR"


class SubtitleSerializationError(SubtitleError):
    default_code = "SUBTITLE_SERIALIZATION_ERROR"


class SubtitleExportError(SubtitleError):
    default_code = "SUBTITLE_EXPORT_ERROR"


class SubtitleTimingError(SubtitleError):
    default_code = "SUBTITLE_TIMING_ERROR"


class SubtitleCoverageError(SubtitleError):
    default_code = "SUBTITLE_COVERAGE_ERROR"


class SubtitleComplexityLimitError(SubtitleError):
    default_code = "SUBTITLE_COMPLEXITY_LIMIT_EXCEEDED"


class SubtitleOutputPathError(SubtitleError):
    default_code = "SUBTITLE_OUTPUT_PATH_INVALID"


class SubtitleOutputCollisionError(SubtitleOutputPathError):
    default_code = "SUBTITLE_OUTPUT_COLLISION"


class SubtitleOutputPreparationError(SubtitleError):
    default_code = "SUBTITLE_OUTPUT_PREPARATION_FAILED"


class SubtitleExistingOutputReadError(SubtitleError):
    default_code = "SUBTITLE_EXISTING_OUTPUT_READ_FAILED"


class SubtitlePublicationError(SubtitleError):
    default_code = "SUBTITLE_PUBLICATION_FAILED"


class SubtitleRollbackError(SubtitleError):
    default_code = "SUBTITLE_ROLLBACK_FAILED"


class GuiError(ProjectError):
    default_code = "GUI_ERROR"


class GuiStateError(GuiError):
    default_code = "GUI_STATE_ERROR"


class PreviewError(GuiError):
    default_code = "PREVIEW_ERROR"


class DesktopActionError(GuiError):
    default_code = "DESKTOP_ACTION_FAILED"


class ExportError(ProjectError):
    default_code = "EXPORT_ERROR"


class ExportValidationError(ExportError):
    default_code = "EXPORT_VALIDATION_ERROR"


class ExportCancellationError(ExportError):
    default_code = "EXPORT_CANCELLED"


class ExportPublicationError(ExportError):
    default_code = "EXPORT_PUBLICATION_ERROR"


class ConfigurationError(ProjectError):
    default_code = "CONFIGURATION_ERROR"


class ExecutableNotFoundError(ConfigurationError):
    default_code = "TOOL_NOT_FOUND"


class PipelineError(ProjectError):
    default_code = "PIPELINE_ERROR"


class PipelineValidationError(PipelineError):
    default_code = "PIPELINE_INPUT_INVALID"


class PipelinePreflightError(PipelineError):
    default_code = "PIPELINE_PREFLIGHT_FAILED"


class PipelineWorkspaceError(PipelineError):
    default_code = "PIPELINE_OUTPUT_INVALID"


class PipelineStageError(PipelineError):
    default_code = "PIPELINE_STAGE_FAILED"


class PipelineArtifactValidationError(PipelineError):
    default_code = "PIPELINE_ARTIFACT_INVALID"


class PipelineManifestError(PipelineError):
    default_code = "PIPELINE_MANIFEST_INVALID"


class PipelinePackageError(PipelineError):
    default_code = "PIPELINE_PACKAGE_INVALID"


class PipelinePublicationError(PipelineError):
    default_code = "PIPELINE_PUBLICATION_FAILED"


class PipelineCancellationError(PipelineError):
    default_code = "PIPELINE_CANCELLED"


class PipelineCleanupError(PipelineError):
    default_code = "PIPELINE_CLEANUP_FAILED"


class PipelinePrivacyError(PipelineArtifactValidationError):
    default_code = "PIPELINE_PRIVACY_VALIDATION_FAILED"


class ScriptInputError(PipelineValidationError):
    default_code = "SCRIPT_INPUT_INVALID"


class LocalModelError(PipelinePreflightError):
    default_code = "LOCAL_WHISPER_MODEL_INVALID"
