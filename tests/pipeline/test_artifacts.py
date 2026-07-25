from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import PipelineArtifactValidationError, PipelineManifestError, PipelinePackageError
from larp_audio_mvp.pipeline.artifacts import read_processing_report, validate_manifest, validate_package

from .test_full_pipeline import make_request, make_service


def _result(tmp_path: Path):
    return make_service([]).run(make_request(tmp_path))


def test_report_rejects_forged_warning_count_and_duration(tmp_path: Path) -> None:
    result = _result(tmp_path)
    payload = json.loads(result.processing_report_path.read_text())
    payload["warning_count"] = 999
    broken = tmp_path / "report.json"; broken.write_text(json.dumps(payload))
    with pytest.raises(PipelineArtifactValidationError): read_processing_report(broken)


@pytest.mark.parametrize("mutation", ("missing_stage", "failed_stage", "configuration_hash", "sample_total"))
def test_report_rejects_inconsistent_stage_and_diagnostic_data(tmp_path: Path, mutation: str) -> None:
    result = _result(tmp_path)
    payload = json.loads(result.processing_report_path.read_text())
    if mutation == "missing_stage":
        payload["stage_results"].pop(3)
    elif mutation == "failed_stage":
        payload["stage_results"][3]["status"] = "failed"
    elif mutation == "configuration_hash":
        payload["configuration"]["sha256"] = "0" * 64
    else:
        for metric in payload["metrics"]:
            if metric[0] == "removed_samples":
                metric[1] += 1
    broken = tmp_path / f"report-{mutation}.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PipelineArtifactValidationError):
        read_processing_report(broken)
    payload["warning_count"] = len(payload["warnings"]); payload["processing_elapsed_milliseconds"] = -1
    broken.write_text(json.dumps(payload))
    with pytest.raises(PipelineArtifactValidationError): read_processing_report(broken)


def test_manifest_rejects_modified_and_unsafe_artifacts(tmp_path: Path) -> None:
    result = _result(tmp_path)
    result.srt_path.write_text("modified", encoding="utf-8")
    with pytest.raises(PipelineManifestError): validate_manifest(result.manifest_path, result.final_output_directory)
    payload = json.loads(result.manifest_path.read_text())
    payload["artifacts"][0]["relative_path"] = "../escape"
    bad = tmp_path / "manifest.json"; bad.write_text(json.dumps(payload))
    with pytest.raises(PipelineManifestError): validate_manifest(bad, result.final_output_directory)


def test_manifest_rejects_missing_required_artifact_and_wrong_schema(tmp_path: Path) -> None:
    result = _result(tmp_path)
    payload = json.loads(result.manifest_path.read_text())
    payload["artifacts"].pop()
    payload["total_artifact_count"] -= 1
    payload["total_artifact_bytes"] = sum(item["size_bytes"] for item in payload["artifacts"])
    broken = tmp_path / "manifest-missing.json"; broken.write_text(json.dumps(payload))
    with pytest.raises(PipelineManifestError): validate_manifest(broken, result.final_output_directory)
    payload = json.loads(result.manifest_path.read_text())
    payload["artifacts"][1]["schema_version"] = "forged"
    broken.write_text(json.dumps(payload))
    with pytest.raises(PipelineManifestError): validate_manifest(broken, result.final_output_directory)


def test_zip_rejects_corruption_and_has_stable_safe_order(tmp_path: Path) -> None:
    result = _result(tmp_path)
    names = validate_package(result.package_zip_path)
    assert names == tuple(sorted(names, key=lambda name: ("cleaned_audio.wav", "edit_map.json", "recognition.json", "alignment.json", "subtitle_blocks.json", "subtitles.srt", "processing_report.json", "manifest.json").index(name)))
    data = bytearray(result.package_zip_path.read_bytes()); data[len(data)//2] ^= 0xFF
    bad = tmp_path / "bad.zip"; bad.write_bytes(data)
    with pytest.raises(PipelinePackageError): validate_package(bad)


def test_zip_rejects_missing_manifest(tmp_path: Path) -> None:
    result = _result(tmp_path)
    broken = tmp_path / "missing-manifest.zip"
    with zipfile.ZipFile(result.package_zip_path) as source, zipfile.ZipFile(broken, "w") as target:
        for item in source.infolist():
            if item.filename != "manifest.json":
                target.writestr(item, source.read(item.filename))
    with pytest.raises(PipelinePackageError):
        validate_package(broken)
