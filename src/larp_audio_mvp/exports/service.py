"""Transactional publication of a cleaned WAV and its gapless SRT."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unicodedata
from collections.abc import Callable
from pathlib import Path

from larp_audio_mvp.core.errors import (
    ExportCancellationError,
    ExportError,
    ExportPublicationError,
)

from .contracts import UniversalExportRequest, UniversalExportResult
from .srt import render_srt, validate_srt
from .validation import validate_request, validate_wav

ProgressCallback = Callable[[str], None]
_WINDOWS_INVALID = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_export_name(value: str) -> str:
    """Preserve meaningful Unicode/spaces while removing filesystem-invalid text."""

    normalized = unicodedata.normalize("NFC", value).strip()
    cleaned = "".join(
        "_" if character in _WINDOWS_INVALID or ord(character) < 32 else character
        for character in normalized
    ).strip(" .")
    if not cleaned or cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        cleaned = "LARP Audio"
    return cleaned[:120].rstrip(" .") or "LARP Audio"


def _check_cancelled(cancellation: object | None) -> None:
    if cancellation is not None and bool(getattr(cancellation, "requested", False)):
        raise ExportCancellationError("Export was cancelled before publication.")


class UniversalExportService:
    """Copy validated artifacts without rerunning any production pipeline stage."""

    def export(
        self,
        request: UniversalExportRequest,
        *,
        progress: ProgressCallback | None = None,
        cancellation: object | None = None,
    ) -> UniversalExportResult:
        notify = progress or (lambda _message: None)
        validate_request(request)
        export_name = safe_export_name(request.base_name)
        audio_path, subtitle_path, export_name = self._available_paths(
            request.destination_folder, export_name
        )
        try:
            staging = Path(
                tempfile.mkdtemp(prefix=".larp-universal-export-", dir=request.destination_folder)
            )
        except OSError as exc:
            raise ExportPublicationError("The selected destination is not writable.") from exc
        staged_audio = staging / audio_path.name
        staged_srt = staging / subtitle_path.name
        published: list[Path] = []
        try:
            notify("Preparing export")
            _check_cancelled(cancellation)
            notify("Copying cleaned audio")
            shutil.copyfile(request.cleaned_audio_source, staged_audio)
            validate_wav(staged_audio, request)
            _check_cancelled(cancellation)
            notify("Writing subtitles")
            payload = render_srt(request.subtitle_document)
            staged_srt.write_bytes(payload)
            validate_srt(staged_srt.read_bytes(), request.subtitle_document)
            _check_cancelled(cancellation)
            notify("Validating files")
            validate_wav(staged_audio, request)
            validate_srt(staged_srt.read_bytes(), request.subtitle_document)
            _check_cancelled(cancellation)
            notify("Publishing export")
            # Hard links atomically fail on collision rather than overwriting. If
            # the second publication fails, the first link is rolled back.
            os.link(staged_audio, audio_path)
            published.append(audio_path)
            os.link(staged_srt, subtitle_path)
            published.append(subtitle_path)
            result = UniversalExportResult(
                export_name=export_name,
                destination_folder=request.destination_folder,
                audio_path=audio_path,
                subtitle_path=subtitle_path,
                audio_sha256=_sha256(audio_path),
                subtitle_sha256=_sha256(subtitle_path),
            )
            notify("Export complete")
            return result
        except ExportError:
            for path in reversed(published):
                path.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as exc:
            for path in reversed(published):
                path.unlink(missing_ok=True)
            raise ExportPublicationError(
                "The WAV and SRT could not be published safely."
            ) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _available_paths(
        destination: Path, base_name: str
    ) -> tuple[Path, Path, str]:
        suffix = 1
        while True:
            candidate = base_name if suffix == 1 else f"{base_name}_{suffix}"
            audio = destination / f"{candidate}_audio.wav"
            subtitles = destination / f"{candidate}_subtitles.srt"
            if not audio.exists() and not subtitles.exists():
                return audio, subtitles, candidate
            suffix += 1
