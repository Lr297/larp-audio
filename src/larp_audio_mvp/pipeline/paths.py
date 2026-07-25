"""Collision-safe run naming, staging, and atomic directory publication."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.core.errors import (
    PipelineCleanupError,
    PipelinePublicationError,
    PipelineWorkspaceError,
)

_WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_run_stem(value: str, *, maximum_length: int = 64) -> str:
    sanitized = _WINDOWS_FORBIDDEN.sub("_", value).strip(" .")
    sanitized = re.sub(r"\s+", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized[:maximum_length].rstrip(" ._")
    return sanitized or "audio"


@dataclass(frozen=True, slots=True)
class PipelinePathPlan:
    output_parent: Path
    run_name: str
    final_directory: Path
    staging_directory: Path

    @classmethod
    def build(
        cls,
        *,
        source_audio: Path,
        script_source: Path | None,
        model_path: Path,
        output_parent: Path,
        name_suffix: str,
        run_id: str,
        run_name_override: str | None = None,
    ) -> "PipelinePathPlan":
        source = source_audio.expanduser().resolve()
        model = model_path.expanduser().resolve()
        raw_parent = output_parent.expanduser().absolute()
        parent = raw_parent.resolve()
        if not parent.exists() or not parent.is_dir():
            raise PipelineWorkspaceError(
                "Output parent must be an existing directory.", code="PIPELINE_OUTPUT_INVALID"
            )
        if raw_parent.is_symlink():
            raise PipelineWorkspaceError(
                "Symlink output directories are not supported.", code="PIPELINE_OUTPUT_INVALID"
            )
        if source == parent:
            raise PipelineWorkspaceError(
                "Input paths must differ from the output parent.", code="PIPELINE_OUTPUT_INVALID"
            )
        if paths_overlap(model, parent):
            raise PipelineWorkspaceError(
                "The output parent and local model directory must not contain one another.",
                code="PIPELINE_MODEL_OUTPUT_OVERLAP",
            )
        if script_source is not None and script_source.expanduser().resolve() == parent:
            raise PipelineWorkspaceError(
                "Script path must differ from the output parent.", code="PIPELINE_OUTPUT_INVALID"
            )
        base = sanitize_run_stem(run_name_override) if run_name_override else f"{sanitize_run_stem(source.stem)}_processed_{sanitize_run_stem(name_suffix, maximum_length=32)}"
        candidate = base
        number = 2
        while (parent / candidate).exists() or any(parent.glob(f".{candidate}.*.partial")):
            candidate = f"{base}_{number}"
            number += 1
        final = parent / candidate
        staging = parent / f".{candidate}.{sanitize_run_stem(run_id, maximum_length=32)}.partial"
        for path in (final, staging):
            if path.exists() or path.is_symlink():
                raise PipelineWorkspaceError(
                    "Planned pipeline path already exists.", code="PIPELINE_OUTPUT_COLLISION"
                )
        if _same_existing(source, staging) or paths_overlap(model, staging):
            raise PipelineWorkspaceError("Pipeline staging collides with an input.")
        return cls(parent, candidate, final, staging)

    def create_staging(self) -> None:
        try:
            self.staging_directory.mkdir(mode=0o700)
        except OSError as exc:
            raise PipelineWorkspaceError(
                "Cannot create the pipeline staging directory.", code="PIPELINE_OUTPUT_INVALID"
            ) from exc
        if self.staging_directory.is_symlink():
            raise PipelineWorkspaceError("Pipeline staging must not be a symlink.")

    def publish(self) -> None:
        if self.final_directory.exists() or self.final_directory.is_symlink():
            raise PipelinePublicationError(
                "Final run directory appeared before publication.", code="PIPELINE_PUBLICATION_FAILED"
            )
        try:
            os.replace(self.staging_directory, self.final_directory)
        except OSError as exc:
            raise PipelinePublicationError(
                "Cannot atomically publish the completed run directory.",
                code="PIPELINE_PUBLICATION_FAILED",
            ) from exc

    def cleanup(self) -> None:
        if not self.staging_directory.exists():
            return
        try:
            if self.staging_directory.is_symlink():
                self.staging_directory.unlink()
            else:
                shutil.rmtree(self.staging_directory)
        except OSError as exc:
            raise PipelineCleanupError(
                f"Cannot remove staging directory: {self.staging_directory}",
                code="PIPELINE_CLEANUP_FAILED",
            ) from exc


def _same_existing(left: Path, right: Path) -> bool:
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def paths_overlap(left: Path, right: Path) -> bool:
    """Return true when either normalized path contains the other."""

    normalized_left = left.expanduser().resolve(strict=False)
    normalized_right = right.expanduser().resolve(strict=False)
    if normalized_left == normalized_right:
        return True
    return (
        normalized_left in normalized_right.parents
        or normalized_right in normalized_left.parents
        or _same_existing(normalized_left, normalized_right)
    )


def paths_equivalent(left: Path, right: Path) -> bool:
    """Compare configured paths after normalization and, where possible, samefile."""

    normalized_left = left.expanduser().resolve(strict=False)
    normalized_right = right.expanduser().resolve(strict=False)
    return normalized_left == normalized_right or _same_existing(
        normalized_left, normalized_right
    )
