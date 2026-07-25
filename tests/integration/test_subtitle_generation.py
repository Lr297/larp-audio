from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from larp_audio_mvp.alignment import ScriptAlignmentService, read_script, write_alignment_atomic
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import (
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
)
from larp_audio_mvp.exports import validate_srt_file
from larp_audio_mvp.subtitles import read_subtitle_document

pytestmark = pytest.mark.integration


def _alignment(
    tmp_path: Path,
    *,
    script_text: str,
    observations: tuple[tuple[str, int, int], ...],
    sample_rate: int = 1_000,
    total_samples: int = 8_000,
) -> Path:
    script = tmp_path / "script.txt"
    script.write_bytes(b"\xef\xbb\xbf" + script_text.encode("utf-8"))
    edit_map = EditMap(
        schema_version="1",
        policy_version="stage-9-integration-v1",
        sample_rate=sample_rate,
        source_total_samples=total_samples + sample_rate,
        output_total_samples=total_samples,
        source_sha256="source-hash",
        output_sha256="cleaned-hash",
        spans=(
            EditSpan(
                EditKind.KEEP,
                SampleRange(0, total_samples // 2),
                SampleRange(0, total_samples // 2),
                reason="keep before pause",
            ),
            EditSpan(
                EditKind.REMOVE,
                SampleRange(total_samples // 2, total_samples // 2 + sample_rate),
                reason="removed pause",
                target_anchor=total_samples // 2,
                candidate_range=SampleRange(
                    total_samples // 2 - 100,
                    total_samples // 2 + sample_rate + 100,
                ),
                retained_before_samples=100,
                retained_after_samples=100,
            ),
            EditSpan(
                EditKind.KEEP,
                SampleRange(total_samples // 2 + sample_rate, total_samples + sample_rate),
                SampleRange(total_samples // 2, total_samples),
                reason="keep after pause",
            ),
        ),
    )

    def original(value: int) -> int:
        return value if value < total_samples // 2 else value + sample_rate

    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language=None,
        sample_rate=sample_rate,
        duration_samples_cleaned=total_samples,
        duration_samples_original=total_samples + sample_rate,
        words=tuple(
            RecognizedWord(
                text=text,
                sample_rate=sample_rate,
                start_sample_cleaned=start,
                end_sample_cleaned=end,
                start_sample_original=original(start),
                end_sample_original=original(end),
                confidence=0.9,
            )
            for text, start, end in observations
        ),
        metadata=(("cleaned_audio_sha256", "cleaned-hash"),),
    )
    result = ScriptAlignmentService(AlignmentSettings()).align(
        read_script(script), recognition, edit_map
    )
    destination = tmp_path / "alignment.json"
    write_alignment_atomic(result, destination)
    return destination


def _run_cli(
    alignment: Path,
    blocks: Path,
    srt: Path,
    *,
    config: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "larp_audio_mvp.app.generate_subtitles",
        "--alignment",
        str(alignment),
        "--blocks-output",
        str(blocks),
        "--srt-output",
        str(srt),
    ]
    if config is not None:
        command.extend(("--config", str(config)))
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _config(tmp_path: Path, **subtitles: object) -> Path:
    path = tmp_path / "config.toml"
    lines = [
        "schema_version = 1",
        "",
        "[paths]",
        'work_directory = "work"',
        'output_root = "output"',
        'model_root = "models"',
        "",
        "[subtitles]",
    ]
    for key, value in subtitles.items():
        if isinstance(value, bool):
            encoded = str(value).lower()
        elif isinstance(value, str):
            encoded = f'"{value}"'
        else:
            encoded = str(value)
        lines.append(f"{key} = {encoded}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_cli_full_path_is_script_preserving_and_deterministic(tmp_path: Path) -> None:
    alignment = _alignment(
        tmp_path,
        script_text="Привет missing мир!\r\nDobrý deň trailing",
        observations=(
            ("Привет", 500, 1_000),
            ("um", 1_100, 1_200),
            ("uh", 1_300, 1_400),
            ("мир", 3_000, 3_500),
            ("Dobrý", 5_000, 5_400),
            ("deň", 5_500, 5_900),
        ),
    )
    original_alignment = alignment.read_bytes()
    blocks = tmp_path / "result" / "subtitle_blocks.json"
    srt = tmp_path / "result" / "subtitles.srt"

    first_run = _run_cli(alignment, blocks, srt)
    assert first_run.returncode == 0, first_run.stderr
    summary = json.loads(first_run.stdout)
    document = read_subtitle_document(blocks)
    validate_srt_file(srt, document)
    first_json = blocks.read_bytes()
    first_srt = srt.read_bytes()

    assert summary["schema_version"] == "subtitle_blocks.schema.v1"
    assert summary["text_coverage"] == "1"
    assert document.exact_script_text == "Привет missing мир!\r\nDobrý deň trailing"
    assert "".join(block.source_text_exact for block in document.blocks) == document.exact_script_text
    assert tuple(
        index for block in document.blocks for index in block.script_word_indices
    ) == tuple(range(document.diagnostics.total_script_words))
    rendered = first_srt.decode("utf-8")
    assert "um" not in rendered and "uh" not in rendered
    assert "Привет" in rendered and "trailing" in rendered
    assert any(block.contains_interpolated_words for block in document.blocks)
    assert any(block.contains_unresolved_words for block in document.blocks)
    assert any(
        block.original_end_sample != block.cleaned_end_sample
        for block in document.blocks
    )

    second_run = _run_cli(alignment, blocks, srt)
    assert second_run.returncode == 0
    assert blocks.read_bytes() == first_json
    assert srt.read_bytes() == first_srt
    assert alignment.read_bytes() == original_alignment
    assert not list(tmp_path.rglob("*.partial.*"))


def test_cli_rejects_unexportable_corrupt_and_impossible_timing(
    tmp_path: Path,
) -> None:
    unresolved_dir = tmp_path / "unresolved"
    unresolved_dir.mkdir()
    unresolved = _alignment(
        unresolved_dir,
        script_text="all words unresolved",
        observations=(),
    )
    failed = _run_cli(
        unresolved,
        unresolved_dir / "blocks.json",
        unresolved_dir / "subtitles.srt",
    )
    assert failed.returncode != 0
    assert "ALL_SUBTITLE_WORDS_UNRESOLVED" in failed.stderr

    coverage_dir = tmp_path / "coverage"
    coverage_dir.mkdir()
    low_coverage = _alignment(
        coverage_dir,
        script_text="before one two after",
        observations=(("after", 3_000, 3_500),),
    )
    coverage_config = _config(
        coverage_dir,
        max_unresolved_words_per_block=3,
        minimum_timing_coverage_for_export=0.5,
    )
    failed = _run_cli(
        low_coverage,
        coverage_dir / "blocks.json",
        coverage_dir / "subtitles.srt",
        config=coverage_config,
    )
    assert failed.returncode != 0
    assert any(
        code in failed.stderr
        for code in (
            "SUBTITLE_TIMING_COVERAGE_TOO_LOW",
            "UNSAFE_UNRESOLVED_SUBTITLE_WORDS",
        )
    )
    assert not (coverage_dir / "blocks.json").exists()
    assert not (coverage_dir / "subtitles.srt").exists()

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    corrupt = _alignment(
        corrupt_dir,
        script_text="hello world",
        observations=(("hello", 500, 1_000), ("world", 1_500, 2_000)),
    )
    payload = json.loads(corrupt.read_text(encoding="utf-8"))
    payload["diagnostics"]["exact_matches"] += 1
    corrupt.write_text(json.dumps(payload), encoding="utf-8")
    failed = _run_cli(
        corrupt, corrupt_dir / "blocks.json", corrupt_dir / "subtitles.srt"
    )
    assert failed.returncode != 0
    assert "DIAGNOSTICS_MISMATCH" in failed.stderr

    timing_dir = tmp_path / "timing"
    timing_dir.mkdir()
    impossible = _alignment(
        timing_dir,
        script_text="one. two.",
        observations=(("one", 0, 1), ("two", 1, 2)),
        sample_rate=48_000,
        total_samples=48_000,
    )
    failed = _run_cli(
        impossible,
        timing_dir / "blocks.json",
        timing_dir / "subtitles.srt",
    )
    assert failed.returncode != 0
    assert "INVALID_SRT_CUE_DURATION" in failed.stderr
    assert not list(tmp_path.rglob("*.partial.*"))


@pytest.mark.parametrize("collision_role", ["blocks", "srt"])
def test_cli_collision_never_changes_alignment(
    tmp_path: Path, collision_role: str
) -> None:
    alignment = _alignment(
        tmp_path,
        script_text="hello world",
        observations=(("hello", 500, 1_000), ("world", 1_500, 2_000)),
    )
    before = alignment.read_bytes()
    blocks = alignment if collision_role == "blocks" else tmp_path / "blocks.json"
    srt = alignment if collision_role == "srt" else tmp_path / "subtitles.srt"
    result = _run_cli(alignment, blocks, srt)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "SUBTITLE_OUTPUT_COLLISION" in result.stderr
    assert "Traceback" not in result.stderr
    assert alignment.read_bytes() == before
    assert json.loads(before)["schema_version"] == "alignment.schema.v2"
    assert not list(tmp_path.rglob("*.partial.*"))


def test_cli_rejects_output_parent_file(tmp_path: Path) -> None:
    alignment = _alignment(
        tmp_path,
        script_text="hello world",
        observations=(("hello", 500, 1_000), ("world", 1_500, 2_000)),
    )
    parent = tmp_path / "parent-file"
    parent.write_text("not a directory", encoding="utf-8")
    result = _run_cli(alignment, parent / "blocks.json", tmp_path / "s.srt")
    assert result.returncode == 2
    assert "SUBTITLE_OUTPUT_PARENT_INVALID" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_scoring_groups_enumeration_into_readable_phrases(tmp_path: Path) -> None:
    observations = tuple(
        (word, 500 + index * 950, 1_000 + index * 950)
        for index, word in enumerate(("One", "two", "three", "four", "five"))
    )
    alignment = _alignment(
        tmp_path,
        script_text="One, two, three, four, five.",
        observations=observations,
        total_samples=6_000,
    )
    blocks = tmp_path / "blocks.json"
    srt = tmp_path / "subtitles.srt"
    result = _run_cli(alignment, blocks, srt)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    # Stage 14.3 treats each genuine list item as an independent cue, even
    # when the source enumeration consists of one-word items.
    assert summary["block_count"] == 5
    assert summary["single_word_blocks"] == 5
