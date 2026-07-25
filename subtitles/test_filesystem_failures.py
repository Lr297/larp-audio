from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import pytest

from larp_audio_mvp.alignment import write_alignment_atomic
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult
from larp_audio_mvp.core.errors import (
    SubtitleExistingOutputReadError,
    SubtitleOutputPreparationError,
    SubtitlePublicationError,
    SubtitleRollbackError,
)
from larp_audio_mvp.subtitles.paths import SubtitlePathPlan
from larp_audio_mvp.subtitles.service import SubtitleGenerationService


def _paths(tmp_path: Path, factory: Callable[..., AlignmentResult]) -> tuple[Path, Path, Path]:
    alignment = tmp_path / "alignment.json"
    write_alignment_atomic(factory("hello world"), alignment)
    return alignment, tmp_path / "blocks.json", tmp_path / "subtitles.srt"


def _generate(alignment: Path, blocks: Path, srt: Path) -> None:
    SubtitleGenerationService().generate(
        alignment_path=alignment,
        blocks_output=blocks,
        srt_output=srt,
        settings=SubtitleSettings(),
    )


def test_directory_creation_permission_is_controlled(
    tmp_path: Path,
    alignment_factory: Callable[..., AlignmentResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alignment, blocks, srt = _paths(tmp_path, alignment_factory)
    blocks = tmp_path / "new" / "blocks.json"
    original = Path.mkdir

    def denied(self: Path, *args: object, **kwargs: object) -> None:
        if self == blocks.parent:
            raise PermissionError("denied")
        original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(SubtitleOutputPreparationError):
        _generate(alignment, blocks, srt)


def test_existing_output_read_permission_is_controlled(
    tmp_path: Path,
    alignment_factory: Callable[..., AlignmentResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alignment, blocks, srt = _paths(tmp_path, alignment_factory)
    blocks.write_text("old", encoding="utf-8")
    original = SubtitlePathPlan._read_existing

    def denied(path: Path, role: str) -> bytes | None:
        if path == blocks.resolve():
            raise SubtitleExistingOutputReadError(
                "denied", code="SUBTITLE_EXISTING_OUTPUT_READ_FAILED"
            ) from PermissionError("denied")
        return original(path, role)

    monkeypatch.setattr(SubtitlePathPlan, "_read_existing", staticmethod(denied))
    with pytest.raises(SubtitleExistingOutputReadError):
        _generate(alignment, blocks, srt)
    assert blocks.read_text(encoding="utf-8") == "old"


def test_invalid_utf8_existing_output_is_not_replaced(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult]
) -> None:
    alignment, blocks, srt = _paths(tmp_path, alignment_factory)
    blocks.write_bytes(b"\xff\xfe")
    srt.write_bytes(b"old srt")
    with pytest.raises(SubtitleExistingOutputReadError):
        _generate(alignment, blocks, srt)
    assert blocks.read_bytes() == b"\xff\xfe"
    assert srt.read_bytes() == b"old srt"


@pytest.mark.parametrize("failed_role", ["subtitle_blocks staging", "SRT staging"])
def test_staging_write_failure_preserves_existing_pair(
    tmp_path: Path,
    alignment_factory: Callable[..., AlignmentResult],
    monkeypatch: pytest.MonkeyPatch,
    failed_role: str,
) -> None:
    alignment, blocks, srt = _paths(tmp_path, alignment_factory)
    blocks.write_bytes(b"old json")
    srt.write_bytes(b"old srt")
    original = SubtitleGenerationService._write_staging

    def fail(path: Path, payload: bytes, *, role: str) -> None:
        if role == failed_role:
            raise SubtitleOutputPreparationError(
                "simulated", code="SUBTITLE_OUTPUT_PREPARATION_FAILED"
            )
        original(path, payload, role=role)

    monkeypatch.setattr(SubtitleGenerationService, "_write_staging", staticmethod(fail))
    with pytest.raises(SubtitleOutputPreparationError):
        _generate(alignment, blocks, srt)
    assert blocks.read_bytes() == b"old json"
    assert srt.read_bytes() == b"old srt"
    assert not list(tmp_path.glob("*.partial.*"))


@pytest.mark.parametrize("replace_failure", [1, 2])
def test_publication_failure_preserves_existing_pair(
    tmp_path: Path,
    alignment_factory: Callable[..., AlignmentResult],
    monkeypatch: pytest.MonkeyPatch,
    replace_failure: int,
) -> None:
    alignment, blocks, srt = _paths(tmp_path, alignment_factory)
    blocks.write_bytes(b"old json")
    srt.write_bytes(b"old srt")
    real_replace = os.replace
    calls = 0

    def fail_once(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == replace_failure:
            raise PermissionError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr("larp_audio_mvp.subtitles.service.os.replace", fail_once)
    with pytest.raises(SubtitlePublicationError):
        _generate(alignment, blocks, srt)
    assert blocks.read_bytes() == b"old json"
    assert srt.read_bytes() == b"old srt"
    assert not list(tmp_path.glob("*.partial.*"))
    assert not list(tmp_path.glob("*.rollback"))


def test_rollback_failure_is_distinct_and_retains_recovery_file(
    tmp_path: Path,
    alignment_factory: Callable[..., AlignmentResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alignment, blocks, srt = _paths(tmp_path, alignment_factory)
    blocks.write_bytes(b"old json")
    srt.write_bytes(b"old srt")
    real_replace = os.replace
    calls = 0

    def fail_publish_and_restore(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise PermissionError("simulated")
        real_replace(source, destination)

    monkeypatch.setattr(
        "larp_audio_mvp.subtitles.service.os.replace", fail_publish_and_restore
    )
    with pytest.raises(SubtitleRollbackError):
        _generate(alignment, blocks, srt)
    assert (tmp_path / "blocks.json.rollback").read_bytes() == b"old json"
