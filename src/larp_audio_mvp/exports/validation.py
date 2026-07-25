"""Strict media validation for the universal WAV + SRT export."""

from __future__ import annotations

import wave
from pathlib import Path

from larp_audio_mvp.core.errors import ExportValidationError

from .contracts import UniversalExportRequest


def validate_request(request: UniversalExportRequest) -> None:
    if not request.base_name.strip():
        raise ExportValidationError("Export name is required.", code="EXPORT_NAME_REQUIRED")
    if request.audio_sample_rate != 48_000 or request.audio_channel_count <= 0:
        raise ExportValidationError(
            "Cleaned audio metadata is unsupported.", code="EXPORT_AUDIO_METADATA_INVALID"
        )
    if request.cleaned_total_samples <= 0:
        raise ExportValidationError(
            "Cleaned audio duration is invalid.", code="EXPORT_AUDIO_DURATION_INVALID"
        )
    if not request.destination_folder.is_dir():
        raise ExportValidationError(
            "Choose an existing destination folder.", code="EXPORT_DESTINATION_INVALID"
        )
    if not request.cleaned_audio_source.is_file():
        raise ExportValidationError("Cleaned audio is missing.", code="EXPORT_AUDIO_MISSING")
    document = request.subtitle_document
    if document.sample_rate != request.audio_sample_rate:
        raise ExportValidationError(
            "Subtitle and audio sample rates differ.", code="EXPORT_TIMELINE_MISMATCH"
        )
    if document.cleaned_total_samples != request.cleaned_total_samples:
        raise ExportValidationError(
            "Subtitle and audio durations differ.", code="EXPORT_TIMELINE_MISMATCH"
        )


def validate_wav(path: Path, request: UniversalExportRequest) -> None:
    try:
        with wave.open(str(path), "rb") as stream:
            actual = (
                stream.getframerate(),
                stream.getnchannels(),
                stream.getnframes(),
                stream.getsampwidth(),
                stream.getcomptype(),
            )
    except (OSError, EOFError, wave.Error) as exc:
        raise ExportValidationError(
            "Exported WAV cannot be read.", code="EXPORT_WAV_INVALID"
        ) from exc
    expected = (
        request.audio_sample_rate,
        request.audio_channel_count,
        request.cleaned_total_samples,
        2,
        "NONE",
    )
    if actual != expected:
        raise ExportValidationError(
            "Exported WAV metadata does not match the processed result.",
            code="EXPORT_WAV_MISMATCH",
        )
