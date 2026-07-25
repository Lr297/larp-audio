"""Generate Stage 9.1 examples through public alignment/subtitle CLIs."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
from pathlib import Path

from larp_audio_mvp.app.align_script import main as align_main
from larp_audio_mvp.app.generate_subtitles import main as subtitle_main
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.core.contracts import (
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
)
from larp_audio_mvp.exports import validate_srt_file
from larp_audio_mvp.models.serialization import write_recognition_atomic
from larp_audio_mvp.subtitles import read_subtitle_document


def generate(root: Path) -> None:
    root = root.resolve()
    examples = root / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    script = examples / "stage_9_1_example_script.txt"
    alignment = examples / "stage_9_1_example_alignment.json"
    blocks = examples / "stage_9_1_example_subtitle_blocks.json"
    srt = examples / "stage_9_1_example_subtitles.srt"
    collision = examples / "stage_9_1_path_collision_error.json"
    comparison = examples / "stage_9_1_scoring_comparison.json"
    exact_text = "One, two, three, four, five.\r\nStop!\r\nПривет, svet!"
    script.write_bytes(exact_text.encode("utf-8"))

    word_values = (
        "One", "two", "three", "four", "five", "Stop", "Привет", "svet"
    )
    starts = (500, 1_450, 2_400, 3_350, 4_300, 6_500, 8_500, 9_450)
    total_samples = 11_000
    edit_map = _identity_edit_map(total_samples)
    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language=None,
        sample_rate=1_000,
        duration_samples_cleaned=total_samples,
        duration_samples_original=total_samples,
        words=tuple(
            RecognizedWord(
                text=text,
                sample_rate=1_000,
                start_sample_cleaned=start,
                end_sample_cleaned=start + 500,
                start_sample_original=start,
                end_sample_original=start + 500,
                confidence=0.9,
            )
            for text, start in zip(word_values, starts)
        ),
        metadata=(("cleaned_audio_sha256", "stage-9-1-cleaned-hash"),),
    )
    work_root = root / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-9-1-example-", dir=work_root) as raw:
        temporary = Path(raw)
        recognition_path = temporary / "recognition.json"
        edit_map_path = temporary / "edit_map.json"
        write_edit_map_atomic(edit_map, edit_map_path)
        write_recognition_atomic(recognition, recognition_path)
        with contextlib.redirect_stdout(io.StringIO()):
            result = align_main(
                [
                    "--script", str(script),
                    "--recognition", str(recognition_path),
                    "--edit-map", str(edit_map_path),
                    "--output", str(alignment),
                ]
            )
        if result:
            raise RuntimeError("Stage 9.1 example alignment CLI failed")

    with contextlib.redirect_stdout(io.StringIO()):
        result = subtitle_main(
            [
                "--alignment", str(alignment),
                "--blocks-output", str(blocks),
                "--srt-output", str(srt),
            ]
        )
    if result:
        raise RuntimeError("Stage 9.1 subtitle CLI failed")
    document = read_subtitle_document(blocks)
    validate_srt_file(srt, document)
    if "".join(block.source_text_exact for block in document.blocks) != exact_text:
        raise RuntimeError("Stage 9.1 example changed exact source text")

    alignment_before = hashlib.sha256(alignment.read_bytes()).hexdigest()
    stderr = io.StringIO()
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = subtitle_main(
            [
                "--alignment", str(alignment),
                "--blocks-output", str(alignment),
                "--srt-output", str(examples / "must-not-exist.srt"),
            ]
        )
    alignment_after = hashlib.sha256(alignment.read_bytes()).hexdigest()
    collision.write_text(
        json.dumps(
            {
                "alignment_sha256_after": alignment_after,
                "alignment_sha256_before": alignment_before,
                "alignment_unchanged": alignment_before == alignment_after,
                "error": stderr.getvalue().strip(),
                "exit_code": exit_code,
                "stdout": stdout.getvalue(),
                "temporary_files": sorted(
                    path.name for path in examples.glob("*.partial.*")
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )
    enumeration = document.blocks[0]
    comparison.write_text(
        json.dumps(
            {
                "input_text": "One, two, three, four, five.",
                "word_timings": [
                    {"end_sample": start + 500, "start_sample": start, "text": text}
                    for text, start in zip(word_values[:5], starts[:5])
                ],
                "previous_problematic_expected_fragmentation": [
                    "One,", "two,", "three,", "four,", "five."
                ],
                "actual_new_result": [enumeration.source_text_exact.rstrip()],
                "block_count": 1,
                "single_word_blocks": 0,
                "diagnostics": {
                    "document_total_blocks": document.diagnostics.total_blocks,
                    "document_single_word_blocks": document.diagnostics.single_word_blocks,
                    "document_short_blocks": document.diagnostics.short_blocks,
                    "average_words_per_block": {
                        "numerator": document.diagnostics.average_words_per_block.numerator,
                        "denominator": document.diagnostics.average_words_per_block.denominator,
                    },
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )
    if exit_code != 2 or alignment_before != alignment_after:
        raise RuntimeError("path collision safety example failed")
    if (examples / "must-not-exist.srt").exists():
        raise RuntimeError("collision run published an output")


def _identity_edit_map(total_samples: int) -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="stage-9-1-example-v1",
        sample_rate=1_000,
        source_total_samples=total_samples,
        output_total_samples=total_samples,
        source_sha256="stage-9-1-source-hash",
        output_sha256="stage-9-1-cleaned-hash",
        spans=(
            EditSpan(
                EditKind.KEEP,
                SampleRange(0, total_samples),
                SampleRange(0, total_samples),
                reason="identity example timeline",
            ),
        ),
    )


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
