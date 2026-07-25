from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import PipelineArtifactValidationError, PipelinePackageError
from larp_audio_mvp.pipeline.artifacts import read_processing_report, validate_package
from tests.pipeline.test_full_pipeline import make_request, make_service


def _result(tmp_path: Path):
    return make_service([]).run(make_request(tmp_path))


@pytest.mark.parametrize(
    "mutation",
    (
        "cancelled", "success_error_code", "failed_without_code", "reversed", "duplicate",
        "report_before_stage", "short_elapsed", "warning_count", "missing_stage", "complete",
        "unknown_status", "artifact_count",
    ),
)
def test_processing_report_corruption_is_controlled(tmp_path: Path, mutation: str) -> None:
    result = _result(tmp_path)
    payload = json.loads(result.processing_report_path.read_text(encoding="utf-8"))
    if mutation == "cancelled": payload["stage_results"][2]["status"] = "cancelled"
    elif mutation == "success_error_code": payload["stage_results"][2]["error_code"] = "ERROR"
    elif mutation == "failed_without_code": payload["stage_results"][2]["status"] = "failed"
    elif mutation == "reversed": payload["stage_results"][1:3] = reversed(payload["stage_results"][1:3])
    elif mutation == "duplicate": payload["stage_results"][2] = deepcopy(payload["stage_results"][1])
    elif mutation == "report_before_stage": payload["report_generated_at"] = "2020-01-01T00:00:00Z"
    elif mutation == "short_elapsed": payload["processing_elapsed_milliseconds"] = 0
    elif mutation == "warning_count": payload["warning_count"] += 1
    elif mutation == "missing_stage": payload["stage_results"].pop()
    elif mutation == "complete": payload["stage_results"][-1]["stage"] = "complete"
    elif mutation == "unknown_status": payload["stage_results"][2]["status"] = "mystery"
    else: payload["artifact_count"] += 1
    broken = tmp_path / f"report-{mutation}.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PipelineArtifactValidationError):
        read_processing_report(broken)


def _rewrite_manifest(source: Path, target: Path, mutate) -> None:
    with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(target, "w") as outgoing:
        for info in incoming.infolist():
            data = incoming.read(info.filename)
            if info.filename == "manifest.json":
                payload = json.loads(data)
                mutate(payload)
                data = json.dumps(payload, sort_keys=True).encode("utf-8")
            outgoing.writestr(info, data)


@pytest.mark.parametrize(
    "mutation",
    (
        "count", "bytes", "role", "media", "required", "timeline", "artifact_schema",
        "run_id", "configuration", "package", "duplicate_role", "missing_role", "unknown_required",
    ),
)
def test_zip_rejects_noncanonical_manifest_metadata(tmp_path: Path, mutation: str) -> None:
    result = _result(tmp_path)
    def mutate(payload):
        if mutation == "count": payload["total_artifact_count"] += 1
        elif mutation == "bytes": payload["total_artifact_bytes"] += 1
        elif mutation == "role": payload["artifacts"][0]["role"] = "other"
        elif mutation == "media": payload["artifacts"][0]["media_type"] = "text/plain"
        elif mutation == "required": payload["artifacts"][0]["required"] = False
        elif mutation == "timeline": payload["artifacts"][0]["timeline"] = "source"
        elif mutation == "artifact_schema": payload["artifacts"][1]["schema_version"] = "forged"
        elif mutation == "run_id": payload["run_id"] = "forged"
        elif mutation == "configuration": payload["configuration_sha256"] = "0" * 64
        elif mutation == "package": payload["package_filename"] = "other.zip"
        elif mutation == "duplicate_role": payload["artifacts"][1]["role"] = payload["artifacts"][0]["role"]
        elif mutation == "missing_role": payload["artifacts"][0]["role"] = ""
        else:
            extra = deepcopy(payload["artifacts"][0]); extra["relative_path"] = "extra.bin"; extra["role"] = "extra"
            payload["artifacts"].append(extra); payload["total_artifact_count"] += 1; payload["total_artifact_bytes"] += extra["size_bytes"]
    broken = tmp_path / f"package-{mutation}.zip"
    _rewrite_manifest(result.package_zip_path, broken, mutate)
    with pytest.raises(PipelinePackageError):
        validate_package(broken)


def test_external_manifest_must_match_package_copy(tmp_path: Path) -> None:
    result = _result(tmp_path)
    external = tmp_path / "manifest.json"
    external.write_text("{}", encoding="utf-8")
    with pytest.raises(PipelinePackageError):
        validate_package(result.package_zip_path, external_manifest_path=external)
