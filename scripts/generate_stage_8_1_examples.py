"""Generate valid and intentionally corrupted Stage 8.1 schema-v2 examples."""

from __future__ import annotations

import codecs
import json
from pathlib import Path

from larp_audio_mvp.alignment import read_alignment
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
from larp_audio_mvp.core.errors import (
    AlignmentSerializationError,
    AlignmentValidationError,
)
from larp_audio_mvp.models.serialization import write_recognition_atomic


def generate(root: Path) -> None:
    examples = root.resolve() / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    script_path = examples / "stage_8_1_example_script.txt"
    recognition_path = examples / "stage_8_1_example_recognition.json"
    edit_map_path = examples / "stage_8_1_example_edit_map.json"
    alignment_path = examples / "stage_8_1_example_alignment.json"
    corrupted_path = examples / "stage_8_1_corrupted_alignment.json"

    script_path.write_bytes(
        codecs.BOM_UTF8 + "Hello missing world\r\nTrailing".encode("utf-8")
    )
    edit_map = _edit_map()
    write_edit_map_atomic(edit_map, edit_map_path)
    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=1_000,
        duration_samples_cleaned=6_000,
        duration_samples_original=7_000,
        words=(
            _word("Hello", 500, 1_000, 0.95),
            _word("um", 1_100, 1_200, None),
            _word("uh", 1_300, 1_400, 0.52),
            _word("world", 3_000, 3_500, 0.91),
        ),
        metadata=tuple(
            sorted(
                {
                    "cleaned_audio_sha256": "stage-8-1-cleaned-hash",
                    "edit_map_output_sha256": "stage-8-1-cleaned-hash",
                    "fixture": "stage-8-1-synthetic-no-model",
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
    valid = read_alignment(alignment_path)
    if not valid.diagnostics.provenance_complete:
        raise RuntimeError("generated valid example has incomplete provenance")
    if not valid.unmatched_asr_words or not valid.rejected_asr_evidence:
        raise RuntimeError("generated example lacks required ASR diagnostic categories")

    corrupted = json.loads(alignment_path.read_text(encoding="utf-8"))
    corrupted["diagnostics"]["exact_matches"] += 1
    corrupted_path.write_text(
        json.dumps(
            corrupted,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        read_alignment(corrupted_path)
    except (AlignmentSerializationError, AlignmentValidationError):
        pass
    else:  # pragma: no cover - generator safety assertion
        raise RuntimeError("strict reader accepted intentionally corrupted example")


def _edit_map() -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="stage-8-1-example-v1",
        sample_rate=1_000,
        source_total_samples=7_000,
        output_total_samples=6_000,
        source_sha256="stage-8-1-source-hash",
        output_sha256="stage-8-1-cleaned-hash",
        spans=(
            EditSpan(
                EditKind.KEEP,
                SampleRange(0, 3_000),
                SampleRange(0, 3_000),
                reason="kept example audio",
            ),
            EditSpan(
                EditKind.REMOVE,
                SampleRange(3_000, 4_000),
                reason="shortened example pause",
                target_anchor=3_000,
                candidate_range=SampleRange(2_750, 4_250),
                retained_before_samples=250,
                retained_after_samples=250,
            ),
            EditSpan(
                EditKind.KEEP,
                SampleRange(4_000, 7_000),
                SampleRange(3_000, 6_000),
                reason="kept example audio",
            ),
        ),
    )


def _word(
    text: str, start: int, end: int, confidence: float | None
) -> RecognizedWord:
    return RecognizedWord(
        text=text,
        sample_rate=1_000,
        start_sample_cleaned=start,
        end_sample_cleaned=end,
        start_sample_original=start if start < 3_000 else start + 1_000,
        end_sample_original=end if end < 3_000 else end + 1_000,
        confidence=confidence,
    )


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
