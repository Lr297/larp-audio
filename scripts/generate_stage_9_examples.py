"""Generate Stage 9 examples through the public alignment and subtitle CLIs."""

from __future__ import annotations

import codecs
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
    script = examples / "stage_9_example_script.txt"
    alignment = examples / "stage_9_example_alignment.json"
    blocks = examples / "stage_9_example_subtitle_blocks.json"
    srt = examples / "stage_9_example_subtitles.srt"
    exact_text = "Привет missing мир!\r\nDobrý deň trailing"
    script.write_bytes(codecs.BOM_UTF8 + exact_text.encode("utf-8"))

    work_root = root / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-9-example-", dir=work_root) as raw:
        temporary = Path(raw)
        recognition_path = temporary / "recognition.json"
        edit_map_path = temporary / "edit_map.json"
        write_edit_map_atomic(_edit_map(), edit_map_path)
        write_recognition_atomic(_recognition(), recognition_path)
        if align_main(
            [
                "--script",
                str(script),
                "--recognition",
                str(recognition_path),
                "--edit-map",
                str(edit_map_path),
                "--output",
                str(alignment),
            ]
        ):
            raise RuntimeError("Stage 9 example alignment CLI failed")

    if subtitle_main(
        [
            "--alignment",
            str(alignment),
            "--blocks-output",
            str(blocks),
            "--srt-output",
            str(srt),
        ]
    ):
        raise RuntimeError("Stage 9 example subtitle CLI failed")
    document = read_subtitle_document(blocks)
    validate_srt_file(srt, document)
    if len(document.blocks) < 2:
        raise RuntimeError("Stage 9 example must contain at least two blocks")
    if not any(block.contains_interpolated_words for block in document.blocks):
        raise RuntimeError("Stage 9 example lacks interpolated timing")
    if not any(block.contains_unresolved_words for block in document.blocks):
        raise RuntimeError("Stage 9 example lacks unresolved attachment")
    if "".join(block.source_text_exact for block in document.blocks) != exact_text:
        raise RuntimeError("Stage 9 example changed exact source text")
    rendered = srt.read_text(encoding="utf-8")
    if "um" in rendered or "uh" in rendered:
        raise RuntimeError("Stage 9 example leaked ASR insertion text")


def _edit_map() -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="stage-9-example-v1",
        sample_rate=1_000,
        source_total_samples=9_000,
        output_total_samples=8_000,
        source_sha256="stage-9-source-hash",
        output_sha256="stage-9-cleaned-hash",
        spans=(
            EditSpan(
                EditKind.KEEP,
                SampleRange(0, 4_000),
                SampleRange(0, 4_000),
                reason="kept example audio",
            ),
            EditSpan(
                EditKind.REMOVE,
                SampleRange(4_000, 5_000),
                reason="shortened example pause",
                target_anchor=4_000,
                candidate_range=SampleRange(3_750, 5_250),
                retained_before_samples=250,
                retained_after_samples=250,
            ),
            EditSpan(
                EditKind.KEEP,
                SampleRange(5_000, 9_000),
                SampleRange(4_000, 8_000),
                reason="kept example audio",
            ),
        ),
    )


def _recognition() -> RecognitionResult:
    return RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language=None,
        sample_rate=1_000,
        duration_samples_cleaned=8_000,
        duration_samples_original=9_000,
        words=(
            _word("Привет", 500, 1_000),
            _word("um", 1_100, 1_200),
            _word("uh", 1_300, 1_400),
            _word("мир", 3_000, 3_500),
            _word("Dobrý", 5_000, 5_400),
            _word("deň", 5_500, 5_900),
        ),
        metadata=(("cleaned_audio_sha256", "stage-9-cleaned-hash"),),
    )


def _word(text: str, start: int, end: int) -> RecognizedWord:
    return RecognizedWord(
        text=text,
        sample_rate=1_000,
        start_sample_cleaned=start,
        end_sample_cleaned=end,
        start_sample_original=start if start < 4_000 else start + 1_000,
        end_sample_original=end if end < 4_000 else end + 1_000,
        confidence=0.9,
    )


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
