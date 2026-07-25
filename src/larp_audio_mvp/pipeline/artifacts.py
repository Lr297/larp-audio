"""Strict deterministic processing report, manifest, and ZIP package support."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zlib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from larp_audio_mvp.core.errors import (
    PipelineArtifactValidationError,
    PipelineManifestError,
    PipelinePackageError,
    ProjectError,
)

from .contracts import (
    ArtifactManifest,
    PipelineArtifact,
    PipelineConfigurationSnapshot,
    PipelineStage,
    PipelineStageResult,
    ProcessingReport,
)
from .privacy import validate_json_payload_privacy

PROCESSING_REPORT_SCHEMA_VERSION = "processing_report.schema.v2"
MANIFEST_SCHEMA_VERSION = "manifest.schema.v1"
ZIP_STREAM_CHUNK_SIZE = 1024 * 1024
ZIP_MAX_ENTRIES = 32
ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES = 32 * 1024 * 1024 * 1024
ZIP_MAX_SINGLE_ENTRY_BYTES = 24 * 1024 * 1024 * 1024
ZIP_MAX_METADATA_BYTES = 16 * 1024 * 1024
ZIP_MAX_COMPRESSION_RATIO = 2_000
PACKAGE_REQUIRED_FILES = (
    "cleaned_audio.wav",
    "edit_map.json",
    "recognition.json",
    "alignment.json",
    "subtitle_blocks.json",
    "subtitles.srt",
    "processing_report.json",
    "manifest.json",
)
MANIFEST_REQUIRED_ARTIFACTS = PACKAGE_REQUIRED_FILES[:-1]
MANIFEST_ARTIFACT_SPECS = (
    ("cleaned_audio.wav", "cleaned_audio", "audio/wav", None, "cleaned"),
    ("edit_map.json", "edit_map", "application/json", "1", "source_to_cleaned"),
    ("recognition.json", "recognition", "application/json", "1", "dual"),
    ("alignment.json", "alignment", "application/json", "alignment.schema.v2", "dual"),
    ("subtitle_blocks.json", "subtitle_blocks", "application/json", "subtitle_blocks.schema.v1", "cleaned"),
    ("subtitles.srt", "subtitles", "application/x-subrip", None, "cleaned"),
    ("processing_report.json", "processing_report", "application/json", PROCESSING_REPORT_SCHEMA_VERSION, None),
)
REPORT_REQUIRED_STAGES = (
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
)
_JSON_SCHEMA_BY_NAME = {
    "edit_map.json": "1",
    "recognition.json": "1",
    "alignment.json": "alignment.schema.v2",
    "subtitle_blocks.json": "subtitle_blocks.schema.v1",
    "processing_report.json": PROCESSING_REPORT_SCHEMA_VERSION,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_processing_report(report: ProcessingReport, path: Path) -> None:
    _write_json_atomic(path, _report_to_dict(report))
    read_processing_report(path)


def read_processing_report(path: Path) -> ProcessingReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != PROCESSING_REPORT_SCHEMA_VERSION:
            raise ValueError("unsupported processing report schema")
        stages = tuple(_stage_from_dict(item) for item in _list(payload, "stage_results"))
        if tuple(item.stage for item in stages) != REPORT_REQUIRED_STAGES:
            raise ValueError("processing report has missing, extra, or out-of-order stages")
        previous_completed: datetime | None = None
        for item in stages:
            stage_started = datetime.fromisoformat(item.started_at.replace("Z", "+00:00"))
            stage_completed = datetime.fromisoformat(item.completed_at.replace("Z", "+00:00"))
            if stage_completed < stage_started:
                raise ValueError("processing stage timestamps are reversed")
            if previous_completed is not None and stage_started < previous_completed:
                raise ValueError("processing stage timestamps are not monotonic")
            previous_completed = stage_completed
            if item.elapsed_milliseconds < 0:
                raise ValueError("processing stage duration is negative")
            if item.status != "success":
                raise ValueError("published processing report contains a non-success stage")
            if item.error_code is not None:
                raise ValueError("successful processing stage contains an error code")
        warnings = tuple(_strings(payload, "warnings"))
        if payload.get("warning_count") != len(warnings):
            raise ValueError("processing warning count is inconsistent")
        started = _timestamp(payload, "processing_started_at")
        completed = _timestamp(payload, "report_generated_at")
        elapsed = _integer(payload, "processing_elapsed_milliseconds")
        if completed < started:
            raise ValueError("processing report timestamps are reversed")
        if previous_completed is not None and completed < previous_completed:
            raise ValueError("report was generated before its final recorded stage")
        if elapsed < sum(item.elapsed_milliseconds for item in stages):
            raise ValueError("processing elapsed duration is shorter than its stages")
        configuration_data = _dict(payload, "configuration")
        values = tuple((str(k), str(v)) for k, v in _list_pairs(configuration_data, "values"))
        config = PipelineConfigurationSnapshot(values=values, sha256=_string(configuration_data, "sha256"))
        if tuple(sorted(values)) != values or len({key for key, _ in values}) != len(values):
            raise ValueError("configuration snapshot is not uniquely sorted")
        config_bytes = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if hashlib.sha256(config_bytes).hexdigest() != config.sha256:
            raise ValueError("configuration snapshot hash is inconsistent")
        report = ProcessingReport(
            schema_version=PROCESSING_REPORT_SCHEMA_VERSION,
            run_id=_nonempty(payload, "run_id"),
            application_version=_nonempty(payload, "application_version"),
            processing_started_at=payload["processing_started_at"],
            report_generated_at=payload["report_generated_at"],
            processing_elapsed_milliseconds=elapsed,
            platform=_nonempty(payload, "platform"),
            python_version=_nonempty(payload, "python_version"),
            source_audio_filename=_nonempty(payload, "source_audio_filename"),
            source_audio_sha256=_sha(payload, "source_audio_sha256"),
            source_audio_size_bytes=_integer(payload, "source_audio_size_bytes"),
            script_sha256=_sha(payload, "script_sha256"),
            script_character_count=_integer(payload, "script_character_count"),
            script_word_count=_integer(payload, "script_word_count"),
            configuration=config,
            stage_results=stages,
            warnings=warnings,
            artifact_names=tuple(_strings(payload, "artifact_names")),
            success=_boolean(payload, "success"),
            metrics=tuple((str(k), v) for k, v in _list_pairs(payload, "metrics")),
        )
        if report.source_audio_size_bytes < 0 or report.script_word_count <= 0:
            raise ValueError("invalid report totals")
        if len(set(report.artifact_names)) != len(report.artifact_names):
            raise ValueError("duplicate report artifact reference")
        if tuple(report.artifact_names) != PACKAGE_REQUIRED_FILES[:6]:
            raise ValueError("report artifact references are incomplete")
        if payload.get("artifact_count") != len(report.artifact_names):
            raise ValueError("processing artifact count is inconsistent")
        if not report.success:
            raise ValueError("published processing report is not successful")
        metrics = dict(report.metrics)
        if len(metrics) != len(report.metrics):
            raise ValueError("duplicate report metric")
        required_metrics = {
            "ffmpeg_version", "ffprobe_version", "model_name", "model_identity",
            "model_path_name", "source_sample_rate", "source_channels",
            "source_total_samples", "cleaned_total_samples", "removed_samples",
            "detected_pause_count", "detected_pause_duration_samples",
            "shortened_pause_count", "recognition_word_count", "subtitle_block_count",
            "alignment_unresolved_words", "alignment_interpolated_words",
            "subtitle_exported_words", "subtitle_unresolved_words",
        }
        if not required_metrics.issubset(metrics):
            raise ValueError("processing diagnostics are incomplete")
        integer_metrics = required_metrics - {"ffmpeg_version", "ffprobe_version", "model_name", "model_identity", "model_path_name"}
        if any(isinstance(metrics[key], bool) or not isinstance(metrics[key], int) or metrics[key] < 0 for key in integer_metrics):
            raise ValueError("processing diagnostic total is invalid")
        if metrics["source_total_samples"] < metrics["cleaned_total_samples"]:
            raise ValueError("processing sample totals are inconsistent")
        if metrics["source_total_samples"] - metrics["cleaned_total_samples"] != metrics["removed_samples"]:
            raise ValueError("processing removed sample total is inconsistent")
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineArtifactValidationError(
            "processing_report.json failed strict validation",
            code="PIPELINE_ARTIFACT_INVALID",
        ) from exc


def build_manifest(
    *,
    run_id: str,
    application_version: str,
    created_at: str,
    source_audio_sha256: str,
    script_sha256: str,
    configuration_sha256: str,
    base_directory: Path,
    artifact_specs: tuple[tuple[str, str, str, str | None, str | None], ...],
) -> ArtifactManifest:
    artifacts = tuple(
        PipelineArtifact(
            relative_path=name,
            role=role,
            media_type=media,
            size_bytes=(base_directory / name).stat().st_size,
            sha256=sha256_file(base_directory / name),
            schema_version=schema,
            timeline=timeline,
        )
        for name, role, media, schema, timeline in artifact_specs
    )
    return ArtifactManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        run_id=run_id,
        application_version=application_version,
        created_at=created_at,
        source_audio_sha256=source_audio_sha256,
        script_sha256=script_sha256,
        configuration_sha256=configuration_sha256,
        artifacts=artifacts,
        total_artifact_count=len(artifacts),
        total_artifact_bytes=sum(item.size_bytes for item in artifacts),
        manifest_filename="manifest.json",
        package_filename="voiceover_package.zip",
    )


def write_manifest(manifest: ArtifactManifest, path: Path) -> None:
    _write_json_atomic(path, _manifest_to_dict(manifest))
    validate_manifest(path, path.parent)


def validate_manifest(path: Path, base_directory: Path) -> ArtifactManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = _parse_manifest_payload(payload)
        root = base_directory.resolve()
        for artifact in manifest.artifacts:
            relative = artifact.relative_path
            pure = PurePosixPath(relative)
            artifact_path = (root / Path(*pure.parts)).resolve()
            if root not in artifact_path.parents or not artifact_path.is_file():
                raise ValueError("manifest artifact is missing or outside run directory")
            if artifact_path.stat().st_size != artifact.size_bytes or sha256_file(artifact_path) != artifact.sha256:
                raise ValueError("manifest artifact size/hash mismatch")
            expected_schema = _JSON_SCHEMA_BY_NAME.get(relative)
            if expected_schema is not None:
                document = json.loads(artifact_path.read_text(encoding="utf-8"))
                if not isinstance(document, dict) or document.get("schema_version") != expected_schema:
                    raise ValueError("artifact JSON schema does not match manifest")
        return manifest
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineManifestError("manifest.json failed strict validation", code="PIPELINE_MANIFEST_INVALID") from exc


def _parse_manifest_payload(payload: Any) -> ArtifactManifest:
    """Validate canonical manifest metadata independently of the filesystem."""

    if not isinstance(payload, dict) or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported manifest schema")
    raw_artifacts = _list(payload, "artifacts")
    if len(raw_artifacts) != len(MANIFEST_ARTIFACT_SPECS):
        raise ValueError("manifest required artifact count is invalid")
    artifacts: list[PipelineArtifact] = []
    seen_paths: set[str] = set()
    seen_roles: set[str] = set()
    for raw, expected in zip(raw_artifacts, MANIFEST_ARTIFACT_SPECS, strict=True):
        if not isinstance(raw, dict):
            raise ValueError("manifest artifact is not an object")
        relative = _nonempty(raw, "relative_path")
        pure = PurePosixPath(relative)
        role = _nonempty(raw, "role")
        if pure.is_absolute() or ".." in pure.parts or relative in seen_paths or role in seen_roles:
            raise ValueError("unsafe or duplicate manifest path/role")
        seen_paths.add(relative)
        seen_roles.add(role)
        schema = raw.get("schema_version")
        timeline = raw.get("timeline")
        expected_name, expected_role, expected_media, expected_schema, expected_timeline = expected
        if (
            relative != expected_name
            or role != expected_role
            or _nonempty(raw, "media_type") != expected_media
            or schema != expected_schema
            or timeline != expected_timeline
            or _boolean(raw, "required") is not True
        ):
            raise ValueError("manifest artifact metadata does not match the canonical specification")
        if schema is not None and not isinstance(schema, str):
            raise TypeError("schema_version")
        if timeline is not None and not isinstance(timeline, str):
            raise TypeError("timeline")
        artifacts.append(
            PipelineArtifact(
                relative_path=relative,
                role=role,
                media_type=expected_media,
                size_bytes=_integer(raw, "size_bytes"),
                sha256=_sha(raw, "sha256"),
                schema_version=schema,
                required=True,
                timeline=timeline,
            )
        )
    if tuple(item.relative_path for item in artifacts) != MANIFEST_REQUIRED_ARTIFACTS:
        raise ValueError("manifest required artifact list/order is invalid")
    if payload.get("total_artifact_count") != len(artifacts):
        raise ValueError("manifest artifact count mismatch")
    if payload.get("total_artifact_bytes") != sum(item.size_bytes for item in artifacts):
        raise ValueError("manifest byte total mismatch")
    if payload.get("manifest_filename") != "manifest.json" or payload.get("package_filename") != "voiceover_package.zip":
        raise ValueError("manifest/package filename policy is invalid")
    _timestamp(payload, "created_at")
    return ArtifactManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        run_id=_nonempty(payload, "run_id"),
        application_version=_nonempty(payload, "application_version"),
        created_at=_nonempty(payload, "created_at"),
        source_audio_sha256=_sha(payload, "source_audio_sha256"),
        script_sha256=_sha(payload, "script_sha256"),
        configuration_sha256=_sha(payload, "configuration_sha256"),
        artifacts=tuple(artifacts),
        total_artifact_count=len(artifacts),
        total_artifact_bytes=sum(item.size_bytes for item in artifacts),
        manifest_filename="manifest.json",
        package_filename="voiceover_package.zip",
    )


def create_package(run_directory: Path, package_path: Path) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".voiceover_package.", suffix=".partial.zip", dir=run_directory)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name in PACKAGE_REQUIRED_FILES:
                source = run_directory / name
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with source.open("rb") as stream, archive.open(info, "w") as target:
                    shutil.copyfileobj(stream, target, length=1024 * 1024)
        validate_package(temporary_path)
        os.replace(temporary_path, package_path)
        validate_package(package_path)
    except (OSError, BadZipFile, KeyError, ValueError, PipelinePackageError) as exc:
        if isinstance(exc, PipelinePackageError):
            raise
        raise PipelinePackageError("voiceover package creation failed", code="PIPELINE_PACKAGE_INVALID") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def validate_package(path: Path, *, external_manifest_path: Path | None = None) -> tuple[str, ...]:
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > ZIP_MAX_ENTRIES:
                raise ValueError("package contains too many entries")
            names = tuple(info.filename for info in infos)
            if names != PACKAGE_REQUIRED_FILES or len(names) != len(set(names)):
                raise ValueError("package file list/order is invalid")
            total_uncompressed = 0
            for info in infos:
                name = info.filename
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts or ".partial" in name or name.endswith(".zip"):
                    raise ValueError("package contains an unsafe path")
                if info.flag_bits & 0x1:
                    raise ValueError("encrypted package entries are not supported")
                if info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ValueError("unsupported ZIP compression method")
                if info.file_size < 0 or info.file_size > ZIP_MAX_SINGLE_ENTRY_BYTES:
                    raise ValueError("package entry exceeds the size limit")
                total_uncompressed += info.file_size
                if total_uncompressed > ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("package exceeds the total size limit")
                if info.file_size and info.compress_size == 0:
                    raise ValueError("invalid ZIP compressed size")
                if info.compress_size and info.file_size / info.compress_size > ZIP_MAX_COMPRESSION_RATIO:
                    raise ValueError("package entry exceeds the compression-ratio limit")
            by_name = {info.filename: info for info in infos}
            manifest_bytes = _read_bounded_entry(archive, by_name["manifest.json"], ZIP_MAX_METADATA_BYTES)
            if external_manifest_path is not None and external_manifest_path.read_bytes() != manifest_bytes:
                raise ValueError("package manifest differs from the published manifest")
            manifest_payload = json.loads(manifest_bytes)
            manifest = _parse_manifest_payload(manifest_payload)
            entries = {item.relative_path: item for item in manifest.artifacts}
            report_payload = json.loads(_read_bounded_entry(archive, by_name["processing_report.json"], ZIP_MAX_METADATA_BYTES))
            if (
                report_payload.get("run_id") != manifest_payload.get("run_id")
                or report_payload.get("application_version") != manifest_payload.get("application_version")
                or report_payload.get("source_audio_sha256") != manifest_payload.get("source_audio_sha256")
                or report_payload.get("script_sha256") != manifest_payload.get("script_sha256")
                or report_payload.get("configuration", {}).get("sha256") != manifest_payload.get("configuration_sha256")
            ):
                raise ValueError("package report/manifest provenance is inconsistent")
            validate_json_payload_privacy(manifest_payload, artifact_name="manifest.json")
            validate_json_payload_privacy(report_payload, artifact_name="processing_report.json")
            with tempfile.TemporaryDirectory(prefix="larp-package-validation-") as temporary:
                extracted_root = Path(temporary)
                for info in infos:
                    size, checksum = _extract_and_hash_zip_entry(
                        archive, info, extracted_root / info.filename
                    )
                    entry = entries.get(info.filename)
                    if entry is not None and (size != entry.size_bytes or checksum != entry.sha256):
                        raise ValueError("package data does not match manifest")
                for json_name in ("edit_map.json", "recognition.json", "alignment.json", "subtitle_blocks.json"):
                    validate_json_payload_privacy(
                        json.loads((extracted_root / json_name).read_text(encoding="utf-8")),
                        artifact_name=json_name,
                    )
                # Import lazily: validation imports this module for the canonical
                # report/manifest readers, so a module-level import would cycle.
                from larp_audio_mvp.alignment import read_alignment
                from larp_audio_mvp.config import AudioSettings
                from .validation import validate_pipeline_artifact_set

                alignment = read_alignment(extracted_root / "alignment.json")
                validate_pipeline_artifact_set(
                    extracted_root,
                    audio_settings=AudioSettings(),
                    expected_script_text=alignment.script.exact_text,
                    expected_script_sha256=alignment.script.source_sha256,
                    expected_source_audio_sha256=manifest.source_audio_sha256,
                    include_report=True,
                    include_manifest=True,
                )
            return names
    except (
        OSError,
        BadZipFile,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        zlib.error,
        ProjectError,
    ) as exc:
        if isinstance(exc, PipelinePackageError):
            raise
        raise PipelinePackageError("voiceover_package.zip failed strict validation", code="PIPELINE_PACKAGE_INVALID") from exc


def _hash_zip_entry(archive: ZipFile, info: ZipInfo) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with archive.open(info, "r") as stream:
        while chunk := stream.read(ZIP_STREAM_CHUNK_SIZE):
            total += len(chunk)
            if total > ZIP_MAX_SINGLE_ENTRY_BYTES or total > info.file_size:
                raise ValueError("ZIP entry expanded beyond its declared size")
            digest.update(chunk)
    if total != info.file_size:
        raise ValueError("ZIP entry size differs from its declaration")
    return total, digest.hexdigest()


def _extract_and_hash_zip_entry(archive: ZipFile, info: ZipInfo, target: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info, "r") as stream, target.open("xb") as output:
        while chunk := stream.read(ZIP_STREAM_CHUNK_SIZE):
            total += len(chunk)
            if total > ZIP_MAX_SINGLE_ENTRY_BYTES or total > info.file_size:
                raise ValueError("ZIP entry expanded beyond its declared size")
            digest.update(chunk)
            output.write(chunk)
    if total != info.file_size:
        raise ValueError("ZIP entry size differs from its declaration")
    return total, digest.hexdigest()


def _read_bounded_entry(archive: ZipFile, info: ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ValueError("ZIP metadata entry exceeds its size limit")
    chunks: list[bytes] = []
    total = 0
    with archive.open(info, "r") as stream:
        while chunk := stream.read(min(ZIP_STREAM_CHUNK_SIZE, limit + 1 - total)):
            total += len(chunk)
            if total > limit or total > info.file_size:
                raise ValueError("ZIP metadata entry exceeds its size limit")
            chunks.append(chunk)
    if total != info.file_size:
        raise ValueError("ZIP metadata entry size differs from its declaration")
    return b"".join(chunks)


def _report_to_dict(report: ProcessingReport) -> dict[str, Any]:
    data = asdict(report)
    data["warning_count"] = len(report.warnings)
    data["artifact_count"] = len(report.artifact_names)
    data["stage_results"] = [_stage_to_dict(item) for item in report.stage_results]
    data["configuration"] = {"values": [list(item) for item in report.configuration.values], "sha256": report.configuration.sha256}
    data["metrics"] = [list(item) for item in report.metrics]
    return data


def _manifest_to_dict(manifest: ArtifactManifest) -> dict[str, Any]:
    return {**asdict(manifest), "artifacts": [asdict(item) for item in manifest.artifacts]}


def _stage_to_dict(item: PipelineStageResult) -> dict[str, Any]:
    data = asdict(item)
    data["stage"] = item.stage.value
    data["metrics"] = [list(pair) for pair in item.metrics]
    return data


def _stage_from_dict(raw: Any) -> PipelineStageResult:
    if not isinstance(raw, dict):
        raise ValueError("stage result is not an object")
    error_code = raw.get("error_code")
    if error_code is not None and (not isinstance(error_code, str) or not error_code):
        raise TypeError("error_code")
    return PipelineStageResult(
        stage=PipelineStage(_nonempty(raw, "stage")),
        status=_nonempty(raw, "status"),
        started_at=_nonempty(raw, "started_at"),
        completed_at=_nonempty(raw, "completed_at"),
        elapsed_milliseconds=_integer(raw, "elapsed_milliseconds"),
        warnings=tuple(_strings(raw, "warnings")),
        artifact_names=tuple(_strings(raw, "artifact_names")),
        metrics=tuple((str(k), v) for k, v in _list_pairs(raw, "metrics")),
        error_code=error_code,
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    try:
        data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        with partial.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except OSError as exc:
        raise PipelineArtifactValidationError("Cannot write pipeline JSON artifact.") from exc
    finally:
        partial.unlink(missing_ok=True)


def _dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data[key]
    if not isinstance(value, dict): raise TypeError(key)
    return value


def _list(data: dict[str, Any], key: str) -> list[Any]:
    value = data[key]
    if not isinstance(value, list): raise TypeError(key)
    return value


def _list_pairs(data: dict[str, Any], key: str) -> list[list[Any]]:
    value = _list(data, key)
    if any(not isinstance(item, list) or len(item) != 2 for item in value): raise TypeError(key)
    return value


def _strings(data: dict[str, Any], key: str) -> list[str]:
    value = _list(data, key)
    if any(not isinstance(item, str) for item in value): raise TypeError(key)
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str): raise TypeError(key)
    return value


def _nonempty(data: dict[str, Any], key: str) -> str:
    value = _string(data, key)
    if not value: raise ValueError(key)
    return value


def _integer(data: dict[str, Any], key: str) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise TypeError(key)
    return value


def _boolean(data: dict[str, Any], key: str) -> bool:
    value = data[key]
    if not isinstance(value, bool): raise TypeError(key)
    return value


def _sha(data: dict[str, Any], key: str) -> str:
    value = _string(data, key)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value): raise ValueError(key)
    return value


def _timestamp(data: dict[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(_string(data, key).replace("Z", "+00:00"))
