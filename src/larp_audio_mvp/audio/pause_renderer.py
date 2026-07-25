"""Atomic FFmpeg rendering driven exclusively by a validated edit map."""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from pathlib import Path

from larp_audio_mvp.audio.probe import FfprobeAdapter
from larp_audio_mvp.audio.process import ProcessRunner
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import AudioInfo, EditKind, EditMap
from larp_audio_mvp.core.errors import AudioRenderError, ProjectError
from larp_audio_mvp.core.logging import get_logger


class FfmpegWavRenderer:
    """Render kept edit-map spans and atomically publish canonical WAV."""

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        probe: FfprobeAdapter,
        ffmpeg_path: Path,
        settings: AudioSettings,
    ) -> None:
        self._runner = runner
        self._probe = probe
        self._ffmpeg_path = ffmpeg_path
        self._settings = settings
        self._logger = get_logger("audio.pause_renderer")

    def render(
        self, audio: AudioInfo, edit_map: EditMap, destination: Path
    ) -> AudioInfo:
        source = audio.source_path.expanduser().resolve()
        destination = destination.expanduser().resolve()
        _validate_render_inputs(audio, edit_map, source, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".partial.wav",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        filter_graph = _build_filter_graph(audio, edit_map)

        self._logger.info(
            "rendering edit map source_file=%s destination_file=%s",
            source.name,
            destination.name,
        )
        try:
            self._runner.run(
                [
                    str(self._ffmpeg_path),
                    "-hide_banner",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-filter_complex",
                    filter_graph,
                    "-map",
                    "[outa]",
                    "-map_metadata",
                    "-1",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-ac",
                    str(audio.channels),
                    "-ar",
                    str(audio.sample_rate),
                    "-c:a",
                    audio.codec_name or self._settings.canonical_codec,
                    "-f",
                    self._settings.canonical_container,
                    str(temporary_path),
                ],
                timeout_seconds=self._settings.subprocess_timeout_seconds,
            )
            rendered = self._probe.probe(temporary_path)
            _validate_rendered_audio(audio, rendered, edit_map)
            os.replace(temporary_path, destination)
            return replace(rendered, source_path=destination)
        except ProjectError:
            raise
        except OSError as exc:
            raise AudioRenderError(
                f"cannot publish cleaned WAV: {destination.name}",
                code="ATOMIC_PUBLISH_FAILED",
            ) from exc
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                self._logger.warning(
                    "could not remove temporary audio file=%s", temporary_path.name
                )


def _build_filter_graph(audio: AudioInfo, edit_map: EditMap) -> str:
    kept = tuple(span for span in edit_map.spans if span.kind is EditKind.KEEP)
    if not kept:
        raise AudioRenderError(
            "edit map contains no kept audio", code="EMPTY_OUTPUT_TIMELINE"
        )
    input_label = f"0:{audio.stream_index}"
    if len(kept) == 1:
        span = kept[0]
        return (
            f"[{input_label}]"
            f"atrim=start_sample={span.source_start}:end_sample={span.source_end},"
            "asetpts=N/SR/TB[outa]"
        )

    split_labels = "".join(f"[split{index}]" for index in range(len(kept)))
    clauses = [f"[{input_label}]asplit={len(kept)}{split_labels}"]
    for index, span in enumerate(kept):
        clauses.append(
            f"[split{index}]"
            f"atrim=start_sample={span.source_start}:end_sample={span.source_end},"
            f"asetpts=N/SR/TB[keep{index}]"
        )
    concat_inputs = "".join(f"[keep{index}]" for index in range(len(kept)))
    clauses.append(f"{concat_inputs}concat=n={len(kept)}:v=0:a=1[outa]")
    return ";".join(clauses)


def _validate_render_inputs(
    audio: AudioInfo, edit_map: EditMap, source: Path, destination: Path
) -> None:
    if not source.exists() or not source.is_file():
        raise AudioRenderError(
            "canonical source WAV does not exist", code="INPUT_NOT_FOUND"
        )
    if source == destination:
        raise AudioRenderError(
            "cleaned WAV destination must differ from source",
            code="INPUT_OVERWRITE_FORBIDDEN",
        )
    if destination.exists() and destination.is_dir():
        raise AudioRenderError(
            "cleaned WAV destination is a directory", code="OUTPUT_IS_DIRECTORY"
        )
    if destination.suffix.lower() != ".wav":
        raise AudioRenderError(
            "cleaned audio destination must use .wav",
            code="INVALID_OUTPUT_EXTENSION",
        )
    if not audio.is_canonical:
        raise AudioRenderError(
            "pause rendering requires canonical WAV", code="NON_CANONICAL_AUDIO"
        )
    if audio.stream_index is None:
        raise AudioRenderError(
            "pause rendering requires stream index", code="MISSING_STREAM_INDEX"
        )
    if audio.total_samples != edit_map.source_total_samples:
        raise AudioRenderError(
            "source sample count does not match edit map",
            code="EDIT_MAP_SOURCE_MISMATCH",
        )
    if audio.sample_rate != edit_map.sample_rate:
        raise AudioRenderError(
            "source sample rate does not match edit map",
            code="EDIT_MAP_SAMPLE_RATE_MISMATCH",
        )
    if audio.sha256 != edit_map.source_sha256:
        raise AudioRenderError(
            "source hash does not match edit map",
            code="EDIT_MAP_SOURCE_HASH_MISMATCH",
        )


def _validate_rendered_audio(
    source: AudioInfo, rendered: AudioInfo, edit_map: EditMap
) -> None:
    if not rendered.is_canonical:
        raise AudioRenderError(
            "rendered WAV is not canonical", code="OUTPUT_FORMAT_MISMATCH"
        )
    for name in ("sample_rate", "channels", "codec_name", "sample_format"):
        if getattr(rendered, name) != getattr(source, name):
            raise AudioRenderError(
                f"rendered WAV changed {name}", code="OUTPUT_FORMAT_MISMATCH"
            )
    if rendered.total_samples != edit_map.output_total_samples:
        raise AudioRenderError(
            "rendered WAV sample count does not match edit map",
            code="OUTPUT_SAMPLE_COUNT_MISMATCH",
        )
    if not rendered.sha256:
        raise AudioRenderError(
            "rendered WAV is missing SHA-256", code="MISSING_OUTPUT_HASH"
        )
