"""Cleaned-timeline SRT renderer and strict standard-library validator."""

from __future__ import annotations

import codecs
import os
import re
from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.core.contracts import SubtitleDocument
from larp_audio_mvp.core.errors import SubtitleExportError, SubtitleTimingError
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing
from larp_audio_mvp.subtitles.validation import validate_subtitle_document

_TIMECODE = re.compile(
    r"^(?P<sh>\d{2,}):(?P<sm>\d{2}):(?P<ss>\d{2}),(?P<sms>\d{3})"
    r" --> "
    r"(?P<eh>\d{2,}):(?P<em>\d{2}):(?P<es>\d{2}),(?P<ems>\d{3})$"
)


@dataclass(frozen=True, slots=True)
class SrtCue:
    index: int
    start_milliseconds: int
    end_milliseconds: int
    lines: tuple[str, ...]
    speech_start_sample: int
    speech_end_sample: int
    display_start_sample: int
    display_end_sample: int


def subtitle_cues(document: SubtitleDocument) -> tuple[SrtCue, ...]:
    """Render the one canonical sample-based gapless display timeline."""

    validate_subtitle_document(document)
    if not document.diagnostics.srt_exportable:
        raise SubtitleExportError(
            "subtitle document is not exportable under its timing policy",
            code="SUBTITLE_NOT_EXPORTABLE",
        )
    cues: list[SrtCue] = []
    timing = apply_gapless_display_timing(document)
    for block, interval in zip(document.blocks, timing):
        cues.append(
            SrtCue(
                index=block.block_index,
                start_milliseconds=interval.srt_start_milliseconds,
                end_milliseconds=interval.srt_end_milliseconds,
                lines=block.display_lines,
                speech_start_sample=interval.speech_start_sample,
                speech_end_sample=interval.speech_end_sample,
                display_start_sample=interval.display_start_sample,
                display_end_sample=interval.display_end_sample,
            )
        )
    return tuple(cues)


def _format_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(document: SubtitleDocument) -> bytes:
    cues = subtitle_cues(document)
    pieces: list[str] = []
    for cue in cues:
        pieces.extend(
            (
                str(cue.index),
                f"{_format_time(cue.start_milliseconds)} --> "
                f"{_format_time(cue.end_milliseconds)}",
                *cue.lines,
                "",
            )
        )
    rendered = "\r\n".join(pieces) + "\r\n"
    payload = rendered.encode("utf-8")
    validate_srt(payload, document)
    return payload


def _parse_time(match: re.Match[str], prefix: str) -> int:
    hours = int(match.group(f"{prefix}h"))
    minutes = int(match.group(f"{prefix}m"))
    seconds = int(match.group(f"{prefix}s"))
    milliseconds = int(match.group(f"{prefix}ms"))
    if minutes >= 60 or seconds >= 60:
        raise SubtitleExportError(
            "SRT timecode minute/second component is out of range",
            code="INVALID_SRT_TIMECODE",
        )
    return ((hours * 60 + minutes) * 60 + seconds) * 1_000 + milliseconds


def validate_srt(payload: bytes, document: SubtitleDocument) -> None:
    """Validate encoding, syntax, cue order, timing, and exact display lines."""

    try:
        if payload.startswith(codecs.BOM_UTF8):
            raise SubtitleExportError(
                "SRT must be UTF-8 without BOM", code="INVALID_SRT_ENCODING"
            )
        text = payload.decode("utf-8")
        if not text.endswith("\r\n"):
            raise SubtitleExportError(
                "SRT must end with CRLF", code="INVALID_SRT_NEWLINES"
            )
        if "\n" in text.replace("\r\n", "") or "\r" in text.replace(
            "\r\n", ""
        ):
            raise SubtitleExportError(
                "SRT contains non-CRLF line endings", code="INVALID_SRT_NEWLINES"
            )
        sections = text[:-4].split("\r\n\r\n") if text.endswith("\r\n\r\n") else []
        if len(sections) != len(document.blocks):
            raise SubtitleExportError(
                "SRT cue count does not match subtitle document",
                code="INVALID_SRT_CUE_COUNT",
            )
        expected = subtitle_cues(document)
        previous_end = -1
        for cue_index, (section, expected_cue) in enumerate(
            zip(sections, expected), start=1
        ):
            lines = section.split("\r\n")
            if len(lines) < 3 or not any(lines[2:]):
                raise SubtitleExportError(
                    "SRT cue text must not be empty", code="INVALID_SRT_CUE_TEXT"
                )
            if lines[0] != str(cue_index):
                raise SubtitleExportError(
                    "SRT cue indices are not sequential",
                    code="INVALID_SRT_CUE_INDEX",
                )
            match = _TIMECODE.fullmatch(lines[1])
            if match is None:
                raise SubtitleExportError(
                    "malformed SRT timecode", code="INVALID_SRT_TIMECODE"
                )
            start = _parse_time(match, "s")
            end = _parse_time(match, "e")
            if end <= start:
                raise SubtitleExportError(
                    "SRT cues overlap or have non-positive duration",
                    code="INVALID_SRT_TIMING",
                )
            if cue_index > 1 and start - previous_end != 1:
                raise SubtitleExportError(
                    "SRT cues are not strictly gapless at the 1 ms boundary",
                    code="INVALID_SRT_GAPLESS_TIMING",
                )
            if (
                start != expected_cue.start_milliseconds
                or end != expected_cue.end_milliseconds
                or tuple(lines[2:]) != expected_cue.lines
            ):
                raise SubtitleExportError(
                    "SRT cue differs from canonical subtitle document",
                    code="SRT_DOCUMENT_MISMATCH",
                )
            previous_end = end
    except SubtitleExportError:
        raise
    except (UnicodeError, IndexError, TypeError, ValueError) as exc:
        raise SubtitleExportError(
            "invalid SRT payload", code="INVALID_SRT"
        ) from exc


def validate_srt_file(path: Path, document: SubtitleDocument) -> None:
    try:
        payload = path.expanduser().resolve().read_bytes()
    except OSError as exc:
        raise SubtitleExportError(
            f"cannot read SRT: {path.name}", code="SRT_READ_FAILED"
        ) from exc
    validate_srt(payload, document)


class SrtExporter:
    @property
    def format_name(self) -> str:
        return "srt"

    def render(self, document: SubtitleDocument) -> bytes:
        return render_srt(document)

    def write(self, document: SubtitleDocument, path: Path) -> None:
        destination = path.expanduser().resolve()
        partial = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.render(document)
        try:
            with partial.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            validate_srt(partial.read_bytes(), document)
            os.replace(partial, destination)
        except (OSError, SubtitleExportError) as exc:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, SubtitleExportError):
                raise
            raise SubtitleExportError(
                f"cannot write SRT: {destination.name}",
                code="SRT_WRITE_FAILED",
            ) from exc
