"""Single orchestration entry point for the complete local voiceover workflow."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from larp_audio_mvp.alignment import write_alignment_atomic
from larp_audio_mvp.alignment.script import count_script_lines
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo, ScriptDocument
from larp_audio_mvp.core.errors import (
    PipelineCancellationError,
    PipelineValidationError,
    ProjectError,
)
from larp_audio_mvp.core.logging import get_logger
from larp_audio_mvp.models import write_recognition_atomic

from .artifacts import (
    MANIFEST_SCHEMA_VERSION,
    PROCESSING_REPORT_SCHEMA_VERSION,
    build_manifest as default_manifest_builder,
    create_package as default_package_writer,
    sha256_file,
    validate_manifest as default_manifest_validator,
    validate_package as default_package_validator,
    write_manifest as default_manifest_writer,
    write_processing_report as default_report_writer,
)
from .cancellation import CancellationToken
from .contracts import (
    EXECUTION_STAGES,
    PipelineCleanupOutcome,
    PipelineConfigurationSnapshot,
    PipelineProgress,
    PipelineRunRequest,
    PipelineRunResult,
    PipelineStage,
    PipelineStageResult,
    PipelineSummary,
    ProcessingReport,
)
from .failures import contextualize_failure
from .paths import PipelinePathPlan, paths_equivalent, paths_overlap
from .privacy import published_script_reference
from .validation import validate_pipeline_artifact_set

LOGGER = get_logger("pipeline.full")
ProgressCallback = Callable[[PipelineProgress], None]


@dataclass(frozen=True, slots=True)
class FullProcessingDependencies:
    audio_loader: object
    pause_detector: object
    pause_remover: object
    recognizer: object
    aligner: object
    subtitle_service: object
    model_preflight: Callable[[object], object]
    tool_preflight: Callable[[], tuple[str, str]] = lambda: ("unknown", "unknown")
    report_writer: Callable[..., object] = default_report_writer
    manifest_builder: Callable[..., object] = default_manifest_builder
    manifest_writer: Callable[..., object] = default_manifest_writer
    package_writer: Callable[..., object] = default_package_writer
    manifest_validator: Callable[..., object] = default_manifest_validator
    package_validator: Callable[..., object] = default_package_validator


class FullProcessingService:
    """Coordinate existing stages and publish only a fully validated run."""

    def __init__(
        self,
        dependencies: FullProcessingDependencies,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        run_id_generator: Callable[[], str] | None = None,
    ) -> None:
        self._deps = dependencies
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._run_id = run_id_generator or (lambda: uuid.uuid4().hex)

    def run(
        self,
        request: PipelineRunRequest,
        *,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> PipelineRunResult:
        token = cancellation or CancellationToken()
        callback = progress or (lambda _progress: None)
        run_id = self._run_id()
        processing_started_at = self._clock()
        processing_started_monotonic = self._monotonic()
        stages: list[PipelineStageResult] = []
        plan: PipelinePathPlan | None = None
        current_stage = PipelineStage.PREFLIGHT
        ffmpeg_version = "unknown"
        ffprobe_version = "unknown"
        model_metadata: object | None = None

        def execute(stage: PipelineStage, message: str, action):
            nonlocal current_stage
            current_stage = stage
            token.check()
            index = EXECUTION_STAGES.index(stage) + 1
            wall_started = self._clock()
            monotonic_started = self._monotonic()
            try:
                callback(PipelineProgress(stage, index, len(EXECUTION_STAGES), message, cancel_requested=token.requested, completed_stage_count=len(stages)))
                token.check()
                value = action()
                token.check()
            except Exception as exc:
                status = "cancelled" if isinstance(exc, PipelineCancellationError) else "failed"
                stages.append(_stage_result(stage, status, wall_started, self._clock(), monotonic_started, self._monotonic(), error_code=getattr(exc, "code", "PIPELINE_STAGE_FAILED")))
                raise
            stages.append(_stage_result(stage, "success", wall_started, self._clock(), monotonic_started, self._monotonic()))
            return value

        try:
            canonical_model_settings = replace(
                request.recognition_settings,
                model_path=request.local_model_path.expanduser().resolve(),
            )

            def preflight() -> None:
                nonlocal ffmpeg_version, ffprobe_version, model_metadata, plan
                _validate_request(request)
                plan = PipelinePathPlan.build(
                    source_audio=request.source_audio_path,
                    script_source=request.script_input.source_path,
                    model_path=request.local_model_path,
                    output_parent=request.output_parent_directory,
                    name_suffix=processing_started_at.strftime("%Y%m%d_%H%M%S"),
                    run_id=run_id,
                    run_name_override=request.output_run_name,
                )
                model_metadata = self._deps.model_preflight(canonical_model_settings)
                ffmpeg_version, ffprobe_version = self._deps.tool_preflight()

            execute(PipelineStage.PREFLIGHT, "Checking local inputs, path safety, model, and media tools", preflight)
            if plan is None:  # pragma: no cover - guarded by successful preflight
                raise PipelineValidationError("Pipeline path plan was not created.")
            execute(PipelineStage.PREPARING_WORKSPACE, "Preparing a private staging workspace", plan.create_staging)

            loader_dependency = self._deps.audio_loader
            loader = loader_dependency(plan.staging_directory) if callable(loader_dependency) else loader_dependency
            source_audio: AudioInfo = execute(
                PipelineStage.ANALYZING_AUDIO,
                "Analyzing source audio without modification",
                lambda: loader.analyze(request.source_audio_path),
            )
            canonical_audio: AudioInfo = execute(
                PipelineStage.CANONICALIZING_AUDIO,
                "Creating canonical mono 48 kHz PCM WAV",
                lambda: loader.canonicalize(source_audio),
            )
            pauses = execute(
                PipelineStage.DETECTING_PAUSES,
                "Detecting eligible silence intervals",
                lambda: self._deps.pause_detector.detect(canonical_audio, settings=request.pause_settings),
            )
            edit_map = execute(
                PipelineStage.SHORTENING_PAUSES,
                "Planning deterministic pause shortening",
                lambda: self._deps.pause_remover.plan(canonical_audio, pauses),
            )
            removal = execute(
                PipelineStage.RENDERING_CLEANED_AUDIO,
                "Rendering cleaned audio from the edit map",
                lambda: self._deps.pause_remover.render(canonical_audio, edit_map, destination=plan.staging_directory / "cleaned_audio.wav"),
            )
            cleaned_audio: AudioInfo = removal.cleaned_audio
            write_edit_map_atomic(removal.edit_map, plan.staging_directory / "edit_map.json")

            recognition = execute(
                PipelineStage.RECOGNIZING_SPEECH,
                "Running local Faster-Whisper word timing",
                lambda: self._deps.recognizer.recognize(cleaned_audio, removal.edit_map, settings=canonical_model_settings),
            )
            recognition_path = plan.staging_directory / "recognition.json"
            write_recognition_atomic(recognition, recognition_path)

            script_reference = published_script_reference(request.script_input)
            script_document = ScriptDocument(
                exact_text=request.script_input.exact_text,
                source_path=Path(script_reference.display_name),
                source_sha256=script_reference.content_sha256,
                encoding=request.script_input.encoding,
                has_bom=request.script_input.has_bom,
                character_count=request.script_input.character_count,
                line_count=count_script_lines(request.script_input.exact_text),
                source_kind=script_reference.source_kind,
                newline_style=script_reference.newline_style,
            )
            alignment = execute(
                PipelineStage.ALIGNING_SCRIPT,
                "Aligning exact original script to ASR timing observations",
                lambda: self._deps.aligner.align(script_document, recognition, removal.edit_map),
            )
            alignment_path = plan.staging_directory / "alignment.json"
            write_alignment_atomic(alignment, alignment_path)

            subtitle_summary = execute(
                PipelineStage.GENERATING_SUBTITLES,
                "Segmenting exact script and publishing subtitle files",
                lambda: self._deps.subtitle_service.generate(
                    alignment_path=alignment_path,
                    blocks_output=plan.staging_directory / "subtitle_blocks.json",
                    srt_output=plan.staging_directory / "subtitles.srt",
                    settings=request.subtitle_settings,
                ),
            )
            stages[-1] = replace(
                stages[-1],
                metrics=(
                    ("policy_version", subtitle_summary.segmentation_policy_version),
                    ("candidate_evaluations", subtitle_summary.candidate_evaluations),
                    ("syntax_analyzer_mode", subtitle_summary.syntax_analyzer_mode),
                    ("candidate_boundary_count", subtitle_summary.candidate_boundary_count),
                    ("legal_boundary_count", subtitle_summary.legal_boundary_count),
                    ("discouraged_boundary_count", subtitle_summary.discouraged_boundary_count),
                    ("forbidden_boundary_count", subtitle_summary.forbidden_boundary_count),
                    ("forced_syntax_split_count", subtitle_summary.forced_syntax_split_count),
                    *subtitle_summary.phase_timings_milliseconds,
                ),
            )

            forbidden_paths = _forbidden_paths(request, plan)
            validated = execute(
                PipelineStage.VALIDATING_ARTIFACTS,
                "Validating schemas, timelines, provenance, and published path privacy",
                lambda: validate_pipeline_artifact_set(
                    plan.staging_directory,
                    audio_settings=request.audio_settings,
                    expected_script_text=request.script_input.exact_text,
                    expected_script_sha256=request.script_input.sha256,
                    expected_source_audio_sha256=sha256_file(request.source_audio_path),
                    canonical_audio_path=canonical_audio.source_path,
                    forbidden_paths=forbidden_paths,
                ),
            )
            subtitle_document = validated.subtitles
            canonical_path = canonical_audio.source_path.resolve()
            if canonical_path != request.source_audio_path.resolve() and plan.staging_directory.resolve() in canonical_path.parents:
                canonical_path.unlink(missing_ok=True)

            config_snapshot = _configuration_snapshot(request)
            base_artifacts = (
                ("cleaned_audio.wav", "cleaned_audio", "audio/wav", None, "cleaned"),
                ("edit_map.json", "edit_map", "application/json", "1", "source_to_cleaned"),
                ("recognition.json", "recognition", "application/json", "1", "dual"),
                ("alignment.json", "alignment", "application/json", alignment.schema_version, "dual"),
                ("subtitle_blocks.json", "subtitle_blocks", "application/json", subtitle_document.schema_version, "cleaned"),
                ("subtitles.srt", "subtitles", "application/x-subrip", None, "cleaned"),
            )
            report_generated_at = self._clock()
            report = ProcessingReport(
                schema_version=PROCESSING_REPORT_SCHEMA_VERSION,
                run_id=run_id,
                application_version=request.application_version,
                processing_started_at=_iso(processing_started_at),
                report_generated_at=_iso(report_generated_at),
                processing_elapsed_milliseconds=_milliseconds(processing_started_monotonic, self._monotonic()),
                platform=platform.platform(),
                python_version=platform.python_version(),
                source_audio_filename=request.source_audio_path.name,
                source_audio_sha256=sha256_file(request.source_audio_path),
                source_audio_size_bytes=request.source_audio_path.stat().st_size,
                script_sha256=request.script_input.sha256,
                script_character_count=request.script_input.character_count,
                script_word_count=request.script_input.script_word_count,
                configuration=config_snapshot,
                stage_results=tuple(stages),
                warnings=tuple(sorted(set(alignment.warnings + subtitle_document.warnings + removal.edit_map.warnings))),
                artifact_names=tuple(item[0] for item in base_artifacts),
                success=True,
                metrics=_metrics(source_audio, pauses, removal, recognition, alignment, subtitle_document, subtitle_summary, ffmpeg_version, ffprobe_version, model_metadata, request),
            )

            def write_reports() -> None:
                self._deps.report_writer(report, plan.staging_directory / "processing_report.json")
                manifest = self._deps.manifest_builder(
                    run_id=run_id,
                    application_version=request.application_version,
                    created_at=_iso(self._clock()),
                    source_audio_sha256=report.source_audio_sha256,
                    script_sha256=request.script_input.sha256,
                    configuration_sha256=config_snapshot.sha256,
                    base_directory=plan.staging_directory,
                    artifact_specs=base_artifacts + (("processing_report.json", "processing_report", "application/json", PROCESSING_REPORT_SCHEMA_VERSION, None),),
                )
                self._deps.manifest_writer(manifest, plan.staging_directory / "manifest.json")

            execute(PipelineStage.WRITING_REPORTS, "Writing processing report and manifest", write_reports)

            def create_and_validate_package() -> None:
                validate_pipeline_artifact_set(
                    plan.staging_directory,
                    audio_settings=request.audio_settings,
                    expected_script_text=request.script_input.exact_text,
                    expected_script_sha256=request.script_input.sha256,
                    expected_source_audio_sha256=report.source_audio_sha256,
                    forbidden_paths=forbidden_paths,
                    include_report=True,
                    include_manifest=True,
                )
                package_path = plan.staging_directory / "voiceover_package.zip"
                self._deps.package_writer(plan.staging_directory, package_path)
                self._deps.package_validator(
                    package_path,
                    external_manifest_path=plan.staging_directory / "manifest.json",
                )

            execute(PipelineStage.CREATING_PACKAGE, "Creating and streaming-validating the voiceover package", create_and_validate_package)
            package_size = (plan.staging_directory / "voiceover_package.zip").stat().st_size
            token.check()
            token.prevent_cancellation()
            execute(PipelineStage.PUBLISHING_RESULTS, "Atomically publishing the completed run", plan.publish)
            final = plan.final_directory
            published_at = _iso(self._clock())
            callback(PipelineProgress(PipelineStage.COMPLETE, len(EXECUTION_STAGES), len(EXECUTION_STAGES), "Processing complete", indeterminate=False, completed_stage_count=len(EXECUTION_STAGES)))
            diagnostics = subtitle_document.diagnostics
            summary = PipelineSummary(
                source_duration_samples=removal.edit_map.source_total_samples,
                cleaned_duration_samples=removal.edit_map.output_total_samples,
                removed_samples=removal.edit_map.removed_samples,
                sample_rate=removal.edit_map.sample_rate,
                detected_pause_count=len(pauses),
                shortened_pause_count=sum(span.kind.value == "remove" for span in removal.edit_map.spans),
                subtitle_block_count=len(subtitle_document.blocks),
                unresolved_word_count=alignment.diagnostics.unresolved_script_words,
                interpolated_word_count=alignment.diagnostics.interpolated_words,
                text_coverage=diagnostics.text_coverage,
                timing_coverage=diagnostics.timing_coverage,
                maximum_characters_per_second=diagnostics.maximum_characters_per_second,
                package_size_bytes=package_size,
            )
            return PipelineRunResult(
                run_id, final, final / "cleaned_audio.wav", final / "edit_map.json",
                final / "recognition.json", final / "alignment.json",
                final / "subtitle_blocks.json", final / "subtitles.srt",
                final / "processing_report.json", final / "manifest.json",
                final / "voiceover_package.zip", report.warnings, tuple(stages),
                summary, subtitle_document, published_at=published_at,
            )
        except Exception as primary_error:
            cleanup = _cleanup_outcome(plan)
            raise contextualize_failure(primary_error, failed_stage=current_stage, cleanup_outcome=cleanup, stage_results=tuple(stages)) from primary_error


def _cleanup_outcome(plan: PipelinePathPlan | None) -> PipelineCleanupOutcome:
    if plan is None:
        return PipelineCleanupOutcome(False, True, None, False, message="No temporary workspace was created.")
    staging = plan.staging_directory
    display = staging.name
    existed = staging.exists() or staging.is_symlink()
    if not existed:
        return PipelineCleanupOutcome(False, True, display, False, message="No temporary workspace remains.")
    cleanup_error: ProjectError | None = None
    try:
        plan.cleanup()
    except ProjectError as exc:
        cleanup_error = exc
        LOGGER.exception("pipeline staging cleanup failed run_id_path=%s", display)
    residual = staging.exists() or staging.is_symlink()
    if cleanup_error is not None or residual:
        code = cleanup_error.code if cleanup_error is not None else "PIPELINE_CLEANUP_INCOMPLETE"
        return PipelineCleanupOutcome(
            True, False, display, residual, code,
            "Temporary workspace cleanup did not complete; manual removal may be required.",
            warnings=("temporary_workspace_may_remain",),
            manual_cleanup_may_be_required=True,
            residual_workspace_path=staging if residual else None,
        )
    return PipelineCleanupOutcome(True, True, display, False, message="Temporary workspace was removed.")


def _validate_request(request: PipelineRunRequest) -> None:
    source = request.source_audio_path.expanduser().resolve()
    model = request.local_model_path.expanduser().resolve()
    output = request.output_parent_directory.expanduser().resolve(strict=False)
    if not source.exists() or not source.is_file():
        raise PipelineValidationError("Source audio file is missing.", code="PIPELINE_INPUT_INVALID")
    if request.script_input.character_count > request.max_script_characters:
        raise PipelineValidationError("Original script is too large.", code="SCRIPT_TOO_LARGE")
    if not request.script_input.exact_text.strip() or request.script_input.script_word_count <= 0:
        raise PipelineValidationError("Original script is empty.", code="SCRIPT_EMPTY")
    if not model.exists():
        raise PipelineValidationError("Local model folder is missing.", code="LOCAL_WHISPER_MODEL_NOT_FOUND")
    if not model.is_dir():
        raise PipelineValidationError("Local model path is not a folder.", code="LOCAL_WHISPER_MODEL_INVALID")
    configured_model = request.recognition_settings.model_path
    if configured_model is not None and not paths_equivalent(model, configured_model):
        raise PipelineValidationError("Recognition settings and request refer to different model directories.", code="PIPELINE_MODEL_PATH_MISMATCH")
    if paths_overlap(model, output):
        raise PipelineValidationError("The output and local model directories must not contain one another.", code="PIPELINE_MODEL_OUTPUT_OVERLAP")


def _forbidden_paths(request: PipelineRunRequest, plan: PipelinePathPlan) -> tuple[Path, ...]:
    values = [request.source_audio_path.parent, request.local_model_path, request.output_parent_directory, plan.staging_directory]
    if request.script_input.source_path is not None:
        values.append(request.script_input.source_path.parent)
    return tuple(values)


def _configuration_snapshot(request: PipelineRunRequest) -> PipelineConfigurationSnapshot:
    alignment_values = tuple((f"alignment.{key}", value) for key, value in request.alignment_settings.snapshot())
    subtitle_values = tuple((f"subtitles.{key}", value) for key, value in request.subtitle_settings.snapshot())
    values = tuple(sorted((
        ("audio.canonical_codec", request.audio_settings.canonical_codec),
        ("audio.canonical_sample_rate", str(request.audio_settings.canonical_sample_rate)),
        ("audio.canonical_channels", str(request.audio_settings.canonical_channels)),
        ("audio.canonical_sample_format", request.audio_settings.canonical_sample_format),
        ("pauses.silence_threshold_db", str(request.pause_settings.silence_threshold_db)),
        ("pauses.minimum_pause_duration_ms", str(request.pause_settings.minimum_pause_duration_ms)),
        ("pauses.shortening_policy_version", str(request.pause_settings.shortening_policy_version)),
        ("pauses.minimum_pause_to_shorten_ms", str(request.pause_settings.minimum_pause_to_shorten_ms)),
        ("pauses.target_remaining_pause_ms", str(request.pause_settings.target_remaining_pause_ms)),
        ("pauses.maximum_removed_per_pause_ms", str(request.pause_settings.maximum_removed_per_pause_ms)),
        ("model.backend", request.recognition_settings.whisper_backend),
        ("model.name", request.recognition_settings.whisper_model or ""),
        ("model.device", request.recognition_settings.device),
        ("model.compute_type", request.recognition_settings.compute_type),
        ("model.language", request.recognition_settings.language or "auto"),
        ("model.beam_size", str(request.recognition_settings.beam_size)),
        *alignment_values, *subtitle_values,
    )))
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PipelineConfigurationSnapshot(values, hashlib.sha256(encoded).hexdigest())


def _metrics(source_audio, pauses, removal, recognition, alignment, subtitles, subtitle_summary, ffmpeg, ffprobe, model_metadata, request):
    model_identity = getattr(model_metadata, "sha256", "synthetic-or-unavailable")
    model_directory = getattr(model_metadata, "directory", request.local_model_path)
    return (
        ("ffmpeg_version", ffmpeg), ("ffprobe_version", ffprobe),
        ("model_identity", str(model_identity)), ("model_path_name", Path(model_directory).name),
        ("model_name", request.recognition_settings.whisper_model or "unknown"),
        ("source_format", source_audio.format_name or "unknown"), ("source_codec", source_audio.codec_name or "unknown"),
        ("source_sample_rate", source_audio.sample_rate), ("source_channels", source_audio.channels),
        ("source_audio_total_samples", source_audio.total_samples or 0),
        ("detected_pause_count", len(pauses)), ("detected_pause_duration_samples", sum(item.length_samples for item in pauses)),
        ("shortened_pause_count", sum(span.kind.value == "remove" for span in removal.edit_map.spans)),
        ("source_total_samples", removal.edit_map.source_total_samples), ("cleaned_total_samples", removal.edit_map.output_total_samples),
        ("removed_samples", removal.edit_map.removed_samples), ("sample_rate", removal.edit_map.sample_rate),
        ("retained_duration_ratio", f"{removal.edit_map.output_total_samples}/{removal.edit_map.source_total_samples}"),
        ("recognition_word_count", len(recognition.words)), ("recognition_language", recognition.language or "unknown"),
        ("alignment_exact_matches", alignment.diagnostics.exact_matches), ("alignment_normalized_matches", alignment.diagnostics.normalized_matches),
        ("alignment_fuzzy_matches", alignment.diagnostics.fuzzy_matches), ("alignment_unresolved_words", alignment.diagnostics.unresolved_script_words),
        ("alignment_interpolated_words", alignment.diagnostics.interpolated_words), ("alignment_provenance_complete", alignment.diagnostics.provenance_complete),
        ("subtitle_block_count", len(subtitles.blocks)), ("subtitle_exported_words", subtitles.diagnostics.exported_script_words),
        ("subtitle_unresolved_words", subtitles.diagnostics.unresolved_script_words),
        ("subtitle_policy_version", subtitle_summary.segmentation_policy_version),
        ("subtitle_candidate_evaluations", subtitle_summary.candidate_evaluations),
        ("subtitle_syntax_analyzer_mode", subtitle_summary.syntax_analyzer_mode),
        ("subtitle_candidate_boundary_count", subtitle_summary.candidate_boundary_count),
        ("subtitle_legal_boundary_count", subtitle_summary.legal_boundary_count),
        ("subtitle_discouraged_boundary_count", subtitle_summary.discouraged_boundary_count),
        ("subtitle_forbidden_boundary_count", subtitle_summary.forbidden_boundary_count),
        ("subtitle_forced_syntax_split_count", subtitles.diagnostics.forced_syntax_split_count),
        ("subtitle_auxiliary_verb_split_count", subtitles.diagnostics.auxiliary_verb_split_count),
        ("subtitle_verb_particle_split_count", subtitles.diagnostics.verb_particle_split_count),
        ("subtitle_compound_noun_split_count", subtitles.diagnostics.compound_noun_split_count),
        ("subtitle_degree_modifier_split_count", subtitles.diagnostics.degree_modifier_split_count),
        ("subtitle_temporal_connector_split_count", subtitles.diagnostics.temporal_connector_split_count),
        ("subtitle_proper_name_split_count", subtitles.diagnostics.proper_name_split_count),
        ("subtitle_internal_gap_count", subtitles.diagnostics.internal_gap_count),
        ("subtitle_srt_gap_count", subtitles.diagnostics.srt_gap_count),
        ("subtitle_overlap_count", subtitles.diagnostics.overlap_count),
        ("subtitle_maximum_internal_gap_ms", subtitles.diagnostics.maximum_internal_gap_ms),
        ("subtitle_maximum_srt_gap_ms", subtitles.diagnostics.maximum_srt_gap_ms),
        ("subtitle_list_item_count", subtitles.diagnostics.list_item_count),
        ("subtitle_list_item_merge_violation_count", subtitles.diagnostics.list_item_merge_violation_count),
        ("subtitle_protected_unit_count", subtitles.diagnostics.protected_unit_count),
        ("subtitle_protected_unit_violation_count", subtitles.diagnostics.protected_unit_violation_count),
        ("subtitle_adjective_noun_split_count", subtitles.diagnostics.adjective_noun_split_count),
        ("subtitle_verb_object_split_count", subtitles.diagnostics.verb_object_split_count),
        ("subtitle_phrasal_verb_split_count", subtitles.diagnostics.phrasal_verb_split_count),
        ("subtitle_preposition_object_split_count", subtitles.diagnostics.preposition_object_split_count),
        ("subtitle_number_unit_split_count", subtitles.diagnostics.number_unit_split_count),
        ("subtitle_product_name_split_count", subtitles.diagnostics.product_name_split_count),
        ("subtitle_maximum_display_characters", subtitles.diagnostics.maximum_display_characters),
        ("subtitle_orphan_fragment_count", subtitles.diagnostics.orphan_fragment_count),
        ("subtitle_incomplete_ending_count", subtitles.diagnostics.incomplete_ending_count),
        ("subtitle_trailing_period_violation_count", subtitles.diagnostics.trailing_period_violation_count),
        ("subtitle_trailing_comma_violation_count", subtitles.diagnostics.trailing_comma_violation_count),
        ("subtitle_three_line_cue_count", subtitles.diagnostics.three_line_cue_count),
        ("subtitle_empty_line_count", subtitles.diagnostics.empty_line_count),
        ("subtitle_maximum_plain_characters", subtitles.diagnostics.maximum_plain_characters),
        ("subtitle_maximum_render_line_characters", subtitles.diagnostics.maximum_render_line_characters),
        ("subtitle_cue_count", subtitles.diagnostics.cue_count),
        ("subtitle_two_line_cue_count", subtitles.diagnostics.two_line_cue_count),
        *tuple(
            (f"subtitle_{name}_milliseconds", value)
            for name, value in subtitle_summary.phase_timings_milliseconds
        ),
    )


def _stage_result(stage, status, wall_start, wall_end, monotonic_start, monotonic_end, error_code=None):
    return PipelineStageResult(stage, status, _iso(wall_start), _iso(wall_end), _milliseconds(monotonic_start, monotonic_end), error_code=error_code)


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _milliseconds(start: float, end: float) -> int:
    return max(0, int(round((end - start) * 1000)))
