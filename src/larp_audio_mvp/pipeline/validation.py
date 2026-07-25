"""Strict cross-artifact validation for one published pipeline run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.alignment import read_alignment
from larp_audio_mvp.audio import read_canonical_wav
from larp_audio_mvp.audio.serialization import read_edit_map
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import (
    AlignmentResult,
    AudioInfo,
    EditMap,
    RecognitionResult,
    SubtitleDocument,
)
from larp_audio_mvp.core.errors import PipelineArtifactValidationError
from larp_audio_mvp.exports import validate_srt_file
from larp_audio_mvp.models import read_recognition
from larp_audio_mvp.subtitles import read_subtitle_document

from .artifacts import read_processing_report, sha256_file, validate_manifest
from .contracts import ArtifactManifest, ProcessingReport
from .privacy import validate_published_artifact_privacy


@dataclass(frozen=True, slots=True)
class ValidatedPipelineArtifactSet:
    cleaned_audio: AudioInfo
    edit_map: EditMap
    recognition: RecognitionResult
    alignment: AlignmentResult
    subtitles: SubtitleDocument
    processing_report: ProcessingReport | None = None
    manifest: ArtifactManifest | None = None


def validate_pipeline_artifact_set(
    run_directory: Path,
    *,
    audio_settings: AudioSettings,
    expected_script_text: str,
    expected_script_sha256: str,
    expected_source_audio_sha256: str,
    canonical_audio_path: Path | None = None,
    forbidden_paths: tuple[Path, ...] = (),
    include_report: bool = False,
    include_manifest: bool = False,
) -> ValidatedPipelineArtifactSet:
    """Validate individual schemas plus all shared identities and timelines."""

    root = run_directory.expanduser().resolve()
    cleaned_path = root / "cleaned_audio.wav"
    edit_path = root / "edit_map.json"
    recognition_path = root / "recognition.json"
    alignment_path = root / "alignment.json"
    subtitles_path = root / "subtitle_blocks.json"
    srt_path = root / "subtitles.srt"

    cleaned = read_canonical_wav(cleaned_path, audio_settings)
    edit_map = read_edit_map(edit_path)
    recognition = read_recognition(recognition_path)
    alignment = read_alignment(alignment_path)
    subtitles = read_subtitle_document(subtitles_path)
    validate_srt_file(srt_path, subtitles)

    _require(cleaned.sha256 == edit_map.output_sha256, "PIPELINE_EDIT_MAP_OUTPUT_HASH_MISMATCH")
    _require(cleaned.sample_rate == edit_map.sample_rate, "PIPELINE_TIMELINE_MISMATCH")
    _require(cleaned.total_samples == edit_map.output_total_samples, "PIPELINE_TIMELINE_MISMATCH")
    if canonical_audio_path is not None:
        _require(
            sha256_file(canonical_audio_path) == edit_map.source_sha256,
            "PIPELINE_EDIT_MAP_SOURCE_HASH_MISMATCH",
        )

    _require(recognition.sample_rate == edit_map.sample_rate, "PIPELINE_TIMELINE_MISMATCH")
    _require(recognition.duration_samples_cleaned == edit_map.output_total_samples, "PIPELINE_TIMELINE_MISMATCH")
    _require(recognition.duration_samples_original == edit_map.source_total_samples, "PIPELINE_TIMELINE_MISMATCH")
    recognition_metadata = dict(recognition.metadata)
    _require(recognition_metadata.get("cleaned_audio_sha256") == cleaned.sha256, "PIPELINE_RECOGNITION_AUDIO_HASH_MISMATCH")
    _require(recognition_metadata.get("edit_map_output_sha256") == edit_map.output_sha256, "PIPELINE_RECOGNITION_EDIT_MAP_MISMATCH")

    _require(alignment.edit_map == edit_map, "PIPELINE_ALIGNMENT_EDIT_MAP_MISMATCH")
    _require(alignment.recognition == recognition, "PIPELINE_ALIGNMENT_RECOGNITION_MISMATCH")
    _require(alignment.script.source_sha256 == expected_script_sha256, "PIPELINE_SCRIPT_PROVENANCE_MISMATCH")
    _require(alignment.script.exact_text == expected_script_text, "PIPELINE_SCRIPT_PROVENANCE_MISMATCH")
    _require(alignment.sample_rate == edit_map.sample_rate, "PIPELINE_TIMELINE_MISMATCH")

    _require(subtitles.source_alignment_sha256 == sha256_file(alignment_path), "PIPELINE_SUBTITLE_ALIGNMENT_HASH_MISMATCH")
    _require(subtitles.script_sha256 == expected_script_sha256, "PIPELINE_SCRIPT_PROVENANCE_MISMATCH")
    _require(subtitles.exact_script_text == expected_script_text, "PIPELINE_SCRIPT_PROVENANCE_MISMATCH")
    _require(subtitles.sample_rate == edit_map.sample_rate, "PIPELINE_TIMELINE_MISMATCH")
    _require(subtitles.cleaned_total_samples == edit_map.output_total_samples, "PIPELINE_TIMELINE_MISMATCH")
    _require(subtitles.original_total_samples == edit_map.source_total_samples, "PIPELINE_TIMELINE_MISMATCH")

    report = read_processing_report(root / "processing_report.json") if include_report else None
    if report is not None:
        _require(report.source_audio_sha256 == expected_source_audio_sha256, "PIPELINE_SOURCE_AUDIO_PROVENANCE_MISMATCH")
        _require(report.script_sha256 == expected_script_sha256, "PIPELINE_SCRIPT_PROVENANCE_MISMATCH")
        metrics = dict(report.metrics)
        _require(metrics.get("source_total_samples") == edit_map.source_total_samples, "PIPELINE_REPORT_TIMELINE_MISMATCH")
        _require(metrics.get("cleaned_total_samples") == edit_map.output_total_samples, "PIPELINE_REPORT_TIMELINE_MISMATCH")
        _require(metrics.get("removed_samples") == edit_map.removed_samples, "PIPELINE_REPORT_TIMELINE_MISMATCH")

    manifest = validate_manifest(root / "manifest.json", root) if include_manifest else None
    if manifest is not None:
        _require(manifest.source_audio_sha256 == expected_source_audio_sha256, "PIPELINE_MANIFEST_PROVENANCE_MISMATCH")
        _require(manifest.script_sha256 == expected_script_sha256, "PIPELINE_MANIFEST_PROVENANCE_MISMATCH")
        if report is not None:
            _require(manifest.run_id == report.run_id, "PIPELINE_MANIFEST_PROVENANCE_MISMATCH")
            _require(manifest.application_version == report.application_version, "PIPELINE_MANIFEST_PROVENANCE_MISMATCH")
            _require(manifest.configuration_sha256 == report.configuration.sha256, "PIPELINE_MANIFEST_PROVENANCE_MISMATCH")

    json_names = ["edit_map.json", "recognition.json", "alignment.json", "subtitle_blocks.json"]
    if include_report:
        json_names.append("processing_report.json")
    if include_manifest:
        json_names.append("manifest.json")
    validate_published_artifact_privacy(
        (root / name for name in json_names), forbidden_paths=forbidden_paths
    )
    return ValidatedPipelineArtifactSet(cleaned, edit_map, recognition, alignment, subtitles, report, manifest)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PipelineArtifactValidationError(
            "Pipeline artifacts have incompatible provenance or timelines.",
            code=code,
        )
