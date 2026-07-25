"""Generate the small Stage 8 interchange examples through public project APIs."""

from __future__ import annotations

import codecs
from pathlib import Path

from larp_audio_mvp.app.align_script import main as align_main
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.core.contracts import (
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
)
from larp_audio_mvp.models.serialization import write_recognition_atomic


def generate(root: Path) -> None:
    examples = root.resolve() / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    script_path = examples / "stage_8_example_script.txt"
    recognition_path = examples / "stage_8_example_recognition.json"
    edit_map_path = examples / "stage_8_example_edit_map.json"
    alignment_path = examples / "stage_8_example_alignment.json"

    script_path.write_bytes(
        codecs.BOM_UTF8
        + "Hello, brave new world!\r\nDon’t alter Привіт. Trailing".encode("utf-8")
    )
    edit_map = EditMap(
        schema_version="1",
        policy_version="stage-8-example-v1",
        sample_rate=1_000,
        source_total_samples=9_000,
        output_total_samples=8_000,
        source_sha256="example-source-audio-sha256",
        output_sha256="example-cleaned-audio-sha256",
        spans=(
            EditSpan(
                EditKind.KEEP,
                SampleRange(0, 2_500),
                SampleRange(0, 2_500),
                reason="kept example audio",
            ),
            EditSpan(
                EditKind.REMOVE,
                SampleRange(2_500, 3_500),
                reason="shortened example pause",
                target_anchor=2_500,
                candidate_range=SampleRange(2_250, 3_750),
                retained_before_samples=250,
                retained_after_samples=250,
            ),
            EditSpan(
                EditKind.KEEP,
                SampleRange(3_500, 9_000),
                SampleRange(2_500, 8_000),
                reason="kept example audio",
            ),
        ),
    )
    write_edit_map_atomic(edit_map, edit_map_path)

    observations = (
        _word("Hello", 500, 900, 0.96),
        _word("brave", 1_000, 1_400, 0.93),
        _word("world", 3_000, 3_500, 0.91),
        _word("don't", 4_000, 4_300, 0.89),
        _word("alter", 4_400, 4_700, None),
        _word("um", 4_800, 4_900, 0.55),
        _word("привіт", 5_000, 5_400, 0.88),
    )
    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=1_000,
        duration_samples_cleaned=8_000,
        duration_samples_original=9_000,
        words=observations,
        metadata=tuple(
            sorted(
                {
                    "cleaned_audio_sha256": "example-cleaned-audio-sha256",
                    "edit_map_output_sha256": "example-cleaned-audio-sha256",
                    "fixture": "stage-8-synthetic-no-model",
                }.items()
            )
        ),
    )
    write_recognition_atomic(recognition, recognition_path)

    exit_code = align_main(
        [
            "--script",
            str(script_path),
            "--recognition",
            str(recognition_path),
            "--edit-map",
            str(edit_map_path),
            "--output",
            str(alignment_path),
        ]
    )
    if exit_code != 0:
        raise SystemExit(exit_code)


def _word(
    text: str, start: int, end: int, confidence: float | None
) -> RecognizedWord:
    return RecognizedWord(
        text=text,
        sample_rate=1_000,
        start_sample_cleaned=start,
        end_sample_cleaned=end,
        start_sample_original=start if start < 2_500 else start + 1_000,
        end_sample_original=end if end < 2_500 else end + 1_000,
        confidence=confidence,
    )


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
