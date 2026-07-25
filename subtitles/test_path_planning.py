from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable

import pytest

from larp_audio_mvp.alignment import read_alignment, write_alignment_atomic
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import AlignmentResult
from larp_audio_mvp.core.errors import (
    SubtitleOutputCollisionError,
    SubtitleOutputPathError,
)
from larp_audio_mvp.subtitles.paths import SubtitlePathPlan
from larp_audio_mvp.subtitles.service import SubtitleGenerationService


def _alignment(
    tmp_path: Path, factory: Callable[..., AlignmentResult]
) -> Path:
    path = tmp_path / "alignment.json"
    write_alignment_atomic(factory("hello world"), path)
    return path


@pytest.mark.parametrize("role", ["blocks", "srt"])
def test_alignment_output_collision_is_rejected_before_write(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult], role: str
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    before = hashlib.sha256(alignment.read_bytes()).hexdigest()
    blocks = alignment if role == "blocks" else tmp_path / "blocks.json"
    srt = alignment if role == "srt" else tmp_path / "subtitles.srt"
    with pytest.raises(SubtitleOutputCollisionError):
        SubtitleGenerationService().generate(
            alignment_path=alignment,
            blocks_output=blocks,
            srt_output=srt,
            settings=SubtitleSettings(),
        )
    assert hashlib.sha256(alignment.read_bytes()).hexdigest() == before
    assert read_alignment(alignment).schema_version == "alignment.schema.v2"
    assert not list(tmp_path.rglob("*.partial.*"))


def test_normalized_dot_and_parent_collisions(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult]
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    for spelling in (
        tmp_path / "." / "alignment.json",
        tmp_path / "child" / ".." / "alignment.json",
    ):
        with pytest.raises(SubtitleOutputCollisionError):
            SubtitlePathPlan.build(
                alignment_path=alignment,
                subtitle_blocks_path=spelling,
                srt_path=tmp_path / "subtitles.srt",
            )


def test_symlink_parent_and_hardlink_collisions(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult]
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    link = tmp_path / "linked"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(SubtitleOutputCollisionError):
        SubtitlePathPlan.build(
            alignment_path=alignment,
            subtitle_blocks_path=link / "alignment.json",
            srt_path=tmp_path / "subtitles.srt",
        )
    hardlink = tmp_path / "hardlink.json"
    try:
        os.link(alignment, hardlink)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    with pytest.raises(SubtitleOutputCollisionError):
        SubtitlePathPlan.build(
            alignment_path=alignment,
            subtitle_blocks_path=hardlink,
            srt_path=tmp_path / "subtitles.srt",
        )


def test_final_output_symlink_is_rejected(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult]
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    target = tmp_path / "target.json"
    target.write_text("target", encoding="utf-8")
    output = tmp_path / "output.json"
    try:
        output.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(SubtitleOutputPathError):
        SubtitlePathPlan.build(
            alignment_path=alignment,
            subtitle_blocks_path=output,
            srt_path=tmp_path / "subtitles.srt",
        )


def test_internal_staging_collision_is_rejected(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult]
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    with pytest.raises(SubtitleOutputCollisionError):
        SubtitlePathPlan.build(
            alignment_path=alignment,
            subtitle_blocks_path=tmp_path / "subtitles.partial.srt",
            srt_path=tmp_path / "subtitles.srt",
        )


@pytest.mark.parametrize("role", ["blocks", "srt"])
def test_output_directory_is_rejected(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult], role: str
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    occupied = tmp_path / f"{role}.out"
    occupied.mkdir()
    with pytest.raises(SubtitleOutputPathError):
        SubtitlePathPlan.build(
            alignment_path=alignment,
            subtitle_blocks_path=occupied if role == "blocks" else tmp_path / "b.json",
            srt_path=occupied if role == "srt" else tmp_path / "s.srt",
        )


def test_missing_and_directory_inputs_are_controlled(tmp_path: Path) -> None:
    for source in (tmp_path / "missing.json", tmp_path / "directory"):
        if source.name == "directory":
            source.mkdir()
        with pytest.raises(SubtitleOutputPathError):
            SubtitlePathPlan.build(
                alignment_path=source,
                subtitle_blocks_path=tmp_path / "b.json",
                srt_path=tmp_path / "s.srt",
            )


def test_parent_component_file_is_rejected(
    tmp_path: Path, alignment_factory: Callable[..., AlignmentResult]
) -> None:
    alignment = _alignment(tmp_path, alignment_factory)
    parent = tmp_path / "not-a-directory"
    parent.write_text("file", encoding="utf-8")
    with pytest.raises(SubtitleOutputPathError):
        SubtitlePathPlan.build(
            alignment_path=alignment,
            subtitle_blocks_path=parent / "b.json",
            srt_path=tmp_path / "s.srt",
        )
