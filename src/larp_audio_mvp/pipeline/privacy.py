"""Safe public source references and structured artifact privacy validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from larp_audio_mvp.core.errors import PipelinePrivacyError

from .contracts import PublishedSourceReference, ScriptInput

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CONTENT_FIELDS = {
    "exact_text",
    "exact_script_text",
    "source_text_exact",
    "display_lines",
    "text",
}


def safe_display_name(path: Path | None, *, fallback: str) -> str:
    raw = path.name if path is not None and path.name else fallback
    value = _WINDOWS_FORBIDDEN.sub("_", raw).strip(" .")[:160]
    return value or fallback


def published_script_reference(script: ScriptInput) -> PublishedSourceReference:
    display = safe_display_name(script.source_path, fallback="user-provided-script.txt")
    return PublishedSourceReference(
        display_name=display,
        logical_role="original_script",
        content_sha256=script.sha256,
        source_kind=script.source_kind.value,
        original_extension=Path(display).suffix.lower(),
        had_bom=script.has_bom,
        newline_style=script.newline_style.value,
    )


def published_audio_reference(path: Path, sha256: str) -> PublishedSourceReference:
    display = safe_display_name(path, fallback="source_audio")
    return PublishedSourceReference(
        display_name=display,
        logical_role="source_audio",
        content_sha256=sha256,
        source_kind="local_file",
        original_extension=Path(display).suffix.lower(),
    )


def validate_published_artifact_privacy(
    json_paths: Iterable[Path],
    *,
    forbidden_paths: Iterable[Path] = (),
) -> None:
    forbidden = tuple(
        str(path.expanduser().resolve())
        for path in forbidden_paths
        if str(path)
    )
    for path in json_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PipelinePrivacyError(
                f"Cannot privacy-check {path.name}.",
                code="PIPELINE_PRIVACY_VALIDATION_FAILED",
            ) from exc
        _inspect(payload, field_name="root", artifact_name=path.name, forbidden=forbidden)


def validate_json_payload_privacy(payload: Any, *, artifact_name: str) -> None:
    """Apply the portable generic path rules to an already decoded document."""

    _inspect(payload, field_name="root", artifact_name=artifact_name, forbidden=())


def _inspect(value: Any, *, field_name: str, artifact_name: str, forbidden: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                _inspect(item, field_name=key, artifact_name=artifact_name, forbidden=forbidden)
        return
    if isinstance(value, list):
        for item in value:
            _inspect(item, field_name=field_name, artifact_name=artifact_name, forbidden=forbidden)
        return
    if not isinstance(value, str) or field_name in _CONTENT_FIELDS:
        return
    lower = value.lower()
    leaked = (
        value.startswith("/")
        or bool(_WINDOWS_ABSOLUTE.match(value))
        or value.startswith("\\\\")
        or lower.startswith("file://")
        or any(candidate and candidate in value for candidate in forbidden)
    )
    if leaked:
        raise PipelinePrivacyError(
            f"Published metadata in {artifact_name} contains a private path in field {field_name}.",
            code="PIPELINE_PRIVACY_VALIDATION_FAILED",
        )
    if "path" in field_name.lower() or "directory" in field_name.lower():
        candidate = Path(value)
        if candidate.is_absolute() or candidate.name != value:
            raise PipelinePrivacyError(
                f"Published path field in {artifact_name} is not a safe basename.",
                code="PIPELINE_PRIVACY_VALIDATION_FAILED",
            )
