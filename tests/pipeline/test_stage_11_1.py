from __future__ import annotations

import json
import zipfile
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import (
    PipelineArtifactValidationError,
    PipelineCleanupError,
    PipelinePackageError,
    PipelinePrivacyError,
    PipelinePublicationError,
    PipelineValidationError,
)
from larp_audio_mvp.pipeline.artifacts import (
    PROCESSING_REPORT_SCHEMA_VERSION,
    read_processing_report,
    validate_package,
)
import larp_audio_mvp.pipeline.artifacts as artifact_module
import larp_audio_mvp.pipeline.service as service_module
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.failures import PipelineRunFailure
from larp_audio_mvp.pipeline.paths import PipelinePathPlan
from larp_audio_mvp.pipeline.privacy import (
    published_script_reference,
    validate_published_artifact_privacy,
)
from larp_audio_mvp.pipeline.service import FullProcessingService
from larp_audio_mvp.pipeline.validation import validate_pipeline_artifact_set

from .test_full_pipeline import make_request, make_service


def test_published_artifacts_keep_script_but_not_private_paths(tmp_path: Path) -> None:
    request = make_request(tmp_path / "private-user-name")
    result = make_service([]).run(request)
    json_paths = tuple(result.final_output_directory.glob("*.json"))
    validate_published_artifact_privacy(
        json_paths,
        forbidden_paths=(tmp_path, request.local_model_path, request.output_parent_directory),
    )
    combined = b"\n".join(path.read_bytes() for path in json_paths)
    assert str(tmp_path).encode() not in combined
    assert b"private-user-name" not in combined
    alignment = json.loads(result.alignment_path.read_text(encoding="utf-8"))
    assert alignment["script"]["source_path"] == "user-provided-script.txt"
    assert alignment["script"]["exact_text"] == request.script_input.exact_text


def test_safe_source_reference_preserves_basename_and_hash(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    script = replace(request.script_input, source_path=tmp_path / "Original сценарий.txt")
    reference = published_script_reference(script)
    assert reference.display_name == "Original сценарий.txt"
    assert reference.content_sha256 == script.sha256
    assert reference.logical_role == "original_script"


@pytest.mark.parametrize("model_inside_output", (True, False))
def test_model_and_output_nesting_is_rejected(tmp_path: Path, model_inside_output: bool) -> None:
    request = make_request(tmp_path / "base")
    if model_inside_output:
        output = tmp_path / "shared"; output.mkdir()
        model = output / "model"; model.mkdir()
    else:
        model = tmp_path / "model-root"; model.mkdir()
        output = model / "exports"; output.mkdir()
    request = replace(
        request,
        local_model_path=model,
        output_parent_directory=output,
        recognition_settings=replace(request.recognition_settings, model_path=model),
    )
    with pytest.raises(PipelineRunFailure) as caught:
        make_service([]).run(request)
    assert caught.value.code == "PIPELINE_MODEL_OUTPUT_OVERLAP"
    assert not caught.value.cleanup_outcome.attempted


def test_duplicate_model_path_mismatch_is_rejected_before_workspace(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    second = tmp_path / "other-model"; second.mkdir()
    request = replace(request, recognition_settings=replace(request.recognition_settings, model_path=second))
    with pytest.raises(PipelineRunFailure) as caught:
        make_service([]).run(request)
    assert caught.value.code == "PIPELINE_MODEL_PATH_MISMATCH"
    assert not any(request.output_parent_directory.iterdir())


def test_primary_failure_and_successful_cleanup_are_both_retained(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    service = make_service([])

    class BrokenRecognizer:
        def recognize(self, *args, **kwargs):
            raise PipelineValidationError("recognition failed", code="SYNTHETIC_RECOGNITION_FAILED")

    service = FullProcessingService(
        replace(service._deps, recognizer=BrokenRecognizer()),  # type: ignore[attr-defined]
        clock=service._clock, monotonic=service._monotonic, run_id_generator=lambda: "failure",  # type: ignore[attr-defined]
    )
    with pytest.raises(PipelineRunFailure) as caught:
        service.run(request)
    failure = caught.value
    assert failure.code == "SYNTHETIC_RECOGNITION_FAILED"
    assert failure.cleanup_outcome.attempted
    assert failure.cleanup_outcome.completed
    assert failure.stage_results[-1].status == "failed"
    assert failure.stage_results[-1].stage.value == "recognizing_speech"
    assert not any(request.output_parent_directory.iterdir())


def test_cleanup_failure_is_secondary_and_residual_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = make_request(tmp_path)
    service = make_service([])

    class BrokenRecognizer:
        def recognize(self, *args, **kwargs):
            raise PipelineValidationError("recognition failed", code="PRIMARY_FAILURE")

    def broken_cleanup(self: PipelinePathPlan) -> None:
        raise PipelineCleanupError("cleanup denied", code="PIPELINE_CLEANUP_FAILED")

    monkeypatch.setattr(PipelinePathPlan, "cleanup", broken_cleanup)
    service = FullProcessingService(
        replace(service._deps, recognizer=BrokenRecognizer()),  # type: ignore[attr-defined]
        clock=service._clock, monotonic=service._monotonic, run_id_generator=lambda: "cleanupfailure",  # type: ignore[attr-defined]
    )
    with pytest.raises(PipelineRunFailure) as caught:
        service.run(request)
    failure = caught.value
    assert failure.code == "PRIMARY_FAILURE"
    assert failure.secondary_error_code == "PIPELINE_CLEANUP_FAILED"
    assert failure.cleanup_outcome.residual_workspace_exists
    assert failure.cleanup_outcome.manual_cleanup_may_be_required
    assert failure.cleanup_outcome.residual_workspace_path is not None


def test_report_v2_has_real_stage_ownership_and_monotonic_durations(tmp_path: Path) -> None:
    result = make_service([]).run(make_request(tmp_path))
    report = read_processing_report(result.processing_report_path)
    assert report.schema_version == PROCESSING_REPORT_SCHEMA_VERSION == "processing_report.schema.v2"
    stages = {item.stage.value: item for item in report.stage_results}
    assert stages["analyzing_audio"].elapsed_milliseconds > 0
    assert stages["canonicalizing_audio"].elapsed_milliseconds > 0
    assert stages["shortening_pauses"].elapsed_milliseconds > 0
    assert stages["rendering_cleaned_audio"].elapsed_milliseconds > 0
    assert report.processing_elapsed_milliseconds >= sum(item.elapsed_milliseconds for item in report.stage_results)


def test_cross_artifact_validator_rejects_cleaned_wav_hash_mismatch(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    result = make_service([]).run(request)
    with result.cleaned_audio_path.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(PipelineArtifactValidationError) as caught:
        validate_pipeline_artifact_set(
            result.final_output_directory,
            audio_settings=request.audio_settings,
            expected_script_text=request.script_input.exact_text,
            expected_script_sha256=request.script_input.sha256,
            expected_source_audio_sha256=hashlib.sha256(request.source_audio_path.read_bytes()).hexdigest(),
        )
    assert caught.value.code == "PIPELINE_EDIT_MAP_OUTPUT_HASH_MISMATCH"


def test_package_validation_streams_and_rejects_unsupported_compression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = make_service([]).run(make_request(tmp_path))
    original_read = zipfile.ZipExtFile.read
    requested: list[int] = []

    def bounded_read(self, n=-1):
        requested.append(n)
        assert n != -1
        return original_read(self, n)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", bounded_read)
    validate_package(result.package_zip_path)
    assert requested and all(value > 0 for value in requested)


def test_package_wide_privacy_scan_rejects_absolute_json_path(tmp_path: Path) -> None:
    result = make_service([]).run(make_request(tmp_path))
    broken = tmp_path / "private.zip"
    with zipfile.ZipFile(result.package_zip_path) as source, zipfile.ZipFile(broken, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "processing_report.json":
                payload = json.loads(data)
                payload["private_path"] = "/absolute/private.wav"
                data = json.dumps(payload).encode()
            target.writestr(info, data)
    with pytest.raises(Exception) as caught:
        validate_package(broken)
    assert getattr(caught.value, "code", None) in {"PIPELINE_PRIVACY_VALIDATION_FAILED", "PIPELINE_PACKAGE_INVALID"}


def test_package_total_size_limit_is_checked_before_entry_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = make_service([]).run(make_request(tmp_path))
    monkeypatch.setattr(artifact_module, "ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(PipelinePackageError):
        validate_package(result.package_zip_path)


def test_report_v1_is_explicitly_rejected(tmp_path: Path) -> None:
    result = make_service([]).run(make_request(tmp_path))
    payload = json.loads(result.processing_report_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "processing_report.schema.v1"
    legacy = tmp_path / "legacy-report.json"
    legacy.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PipelineArtifactValidationError):
        read_processing_report(legacy)


def test_privacy_failure_cleans_staging_and_publishes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = make_request(tmp_path)

    def reject(*args, **kwargs):
        raise PipelinePrivacyError("private path", code="PIPELINE_PRIVACY_VALIDATION_FAILED")

    monkeypatch.setattr(service_module, "validate_pipeline_artifact_set", reject)
    with pytest.raises(PipelineRunFailure) as caught:
        make_service([]).run(request)
    assert caught.value.code == "PIPELINE_PRIVACY_VALIDATION_FAILED"
    assert caught.value.cleanup_outcome.completed
    assert not any(request.output_parent_directory.iterdir())


def test_manifest_provenance_mismatch_has_controlled_code(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    result = make_service([]).run(request)
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    payload["source_audio_sha256"] = "0" * 64
    result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PipelineArtifactValidationError) as caught:
        validate_pipeline_artifact_set(
            result.final_output_directory,
            audio_settings=request.audio_settings,
            expected_script_text=request.script_input.exact_text,
            expected_script_sha256=request.script_input.sha256,
            expected_source_audio_sha256=hashlib.sha256(request.source_audio_path.read_bytes()).hexdigest(),
            include_report=True,
            include_manifest=True,
        )
    assert caught.value.code == "PIPELINE_MANIFEST_PROVENANCE_MISMATCH"


def test_publication_failure_leaves_no_partial_final_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = make_request(tmp_path)

    def reject_publication(self: PipelinePathPlan) -> None:
        raise PipelinePublicationError("publication denied", code="PIPELINE_PUBLICATION_FAILED")

    monkeypatch.setattr(PipelinePathPlan, "publish", reject_publication)
    with pytest.raises(PipelineRunFailure) as caught:
        make_service([]).run(request)
    assert caught.value.code == "PIPELINE_PUBLICATION_FAILED"
    assert caught.value.failed_stage.value == "publishing_results"
    assert caught.value.cleanup_outcome.completed
    assert not any(request.output_parent_directory.iterdir())


def test_cancellation_at_package_boundary_does_not_create_package(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    calls: list[str] = []
    token = CancellationToken()

    def progress(item) -> None:
        if item.stage.value == "creating_package":
            token.request()

    with pytest.raises(Exception) as caught:
        make_service(calls).run(request, progress=progress, cancellation=token)
    assert getattr(caught.value, "code", None) == "PIPELINE_CANCELLED"
    assert "package" not in calls
    assert not any(request.output_parent_directory.iterdir())
