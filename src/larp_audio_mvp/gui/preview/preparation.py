"""Heavy read-only preparation performed before media is loaded."""

from __future__ import annotations

from larp_audio_mvp.alignment import read_alignment
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.pipeline.artifacts import read_processing_report, sha256_file, validate_package
from larp_audio_mvp.pipeline.contracts import PipelineRunResult
from larp_audio_mvp.pipeline.validation import validate_pipeline_artifact_set
from larp_audio_mvp.subtitles import read_subtitle_document

from .contracts import PreviewSource
from .diagnostics import build_preview_diagnostics


class PreviewPreparationService:
    def prepare(self, result: PipelineRunResult) -> PreviewSource:
        alignment = read_alignment(result.alignment_path)
        validated = validate_pipeline_artifact_set(
            result.final_output_directory,
            audio_settings=AudioSettings(),
            expected_script_text=alignment.script.exact_text,
            expected_script_sha256=alignment.script.source_sha256,
            expected_source_audio_sha256=read_processing_report(result.processing_report_path).source_audio_sha256,
            include_report=True,
            include_manifest=True,
        )
        validate_package(result.package_zip_path, external_manifest_path=result.manifest_path)
        document = read_subtitle_document(result.subtitle_blocks_path)
        report = validated.processing_report
        assert report is not None
        return PreviewSource(
            result.cleaned_audio_path, document, validated.cleaned_audio.sample_rate,
            validated.cleaned_audio.total_samples or 0, validated.cleaned_audio.sha256 or "",
            sha256_file(result.subtitle_blocks_path), result.run_id, "pipeline_run_result",
            build_preview_diagnostics(result, report),
        )
