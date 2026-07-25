from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from larp_audio_mvp.alignment import write_alignment_atomic
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult, SubtitleDocument
from larp_audio_mvp.core.errors import SubtitleExportError
from larp_audio_mvp.core.errors import SubtitleOutputCollisionError
from larp_audio_mvp.subtitles.service import SubtitleGenerationService


class _FailingExporter:
    def render(self, document: SubtitleDocument) -> bytes:
        raise SubtitleExportError("artificial export failure", code="TEST_FAILURE")


def test_two_artifact_service_preserves_existing_outputs_on_failure(
    alignment_factory: Callable[..., AlignmentResult], tmp_path: Path
) -> None:
    alignment = alignment_factory("hello world")
    alignment_path = tmp_path / "alignment.json"
    write_alignment_atomic(alignment, alignment_path)
    blocks = tmp_path / "subtitle_blocks.json"
    srt = tmp_path / "subtitles.srt"
    blocks.write_bytes(b"previous json")
    srt.write_bytes(b"previous srt")

    service = SubtitleGenerationService(exporter=_FailingExporter())  # type: ignore[arg-type]
    with pytest.raises(SubtitleExportError) as captured:
        service.generate(
            alignment_path=alignment_path,
            blocks_output=blocks,
            srt_output=srt,
            settings=SubtitleSettings(),
        )
    assert captured.value.code == "TEST_FAILURE"
    assert blocks.read_bytes() == b"previous json"
    assert srt.read_bytes() == b"previous srt"
    assert not list(tmp_path.glob("*.partial.*"))


def test_two_artifact_service_rejects_same_destination(
    alignment_factory: Callable[..., AlignmentResult], tmp_path: Path
) -> None:
    alignment_path = tmp_path / "alignment.json"
    write_alignment_atomic(alignment_factory("hello"), alignment_path)
    with pytest.raises(SubtitleOutputCollisionError) as captured:
        SubtitleGenerationService().generate(
            alignment_path=alignment_path,
            blocks_output=tmp_path / "same.out",
            srt_output=tmp_path / "same.out",
            settings=SubtitleSettings(),
        )
    assert captured.value.code == "SUBTITLE_OUTPUT_COLLISION"
