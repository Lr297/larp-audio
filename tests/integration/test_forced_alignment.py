from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from larp_audio_mvp.app.align_script import main
from larp_audio_mvp.alignment import read_alignment
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
from larp_audio_mvp.core.errors import (
    AlignmentSerializationError,
    AlignmentValidationError,
)

pytestmark = pytest.mark.integration


def _edit_map() -> EditMap:
    return EditMap(
        schema_version="1",
        policy_version="integration-v1",
        sample_rate=1_000,
        source_total_samples=7_000,
        output_total_samples=6_000,
        source_sha256="source-example-hash",
        output_sha256="cleaned-example-hash",
        spans=(
            EditSpan(EditKind.KEEP, SampleRange(0, 3_000), SampleRange(0, 3_000), reason="keep"),
            EditSpan(
                EditKind.REMOVE,
                SampleRange(3_000, 4_000),
                reason="pause",
                target_anchor=3_000,
                candidate_range=SampleRange(2_750, 4_250),
                retained_before_samples=250,
                retained_after_samples=250,
            ),
            EditSpan(EditKind.KEEP, SampleRange(4_000, 7_000), SampleRange(3_000, 6_000), reason="keep"),
        ),
    )


def _recognized(
    text: str, start: int, end: int, confidence: float | None = None
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


def test_full_cli_path_preserves_script_and_writes_stable_alignment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script_bytes = "Hello, missing world!\r\nTrailing…".encode("utf-8")
    script = tmp_path / "script ü.txt"
    script.write_bytes(script_bytes)
    edit_map_path = tmp_path / "edit map.json"
    write_edit_map_atomic(_edit_map(), edit_map_path)
    recognition = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="en",
        sample_rate=1_000,
        duration_samples_cleaned=6_000,
        duration_samples_original=7_000,
        words=(
            _recognized("Hello", 500, 1_000, 0.9),
            _recognized("um", 1_100, 1_200, None),
            _recognized("uh", 1_300, 1_400, None),
            _recognized("world", 3_000, 3_500, 0.8),
        ),
        metadata=tuple(
            sorted(
                {
                    "cleaned_audio_sha256": "cleaned-example-hash",
                    "edit_map_output_sha256": "cleaned-example-hash",
                }.items()
            )
        ),
    )
    recognition_path = tmp_path / "recognition.json"
    write_recognition_atomic(recognition, recognition_path)
    output_one = tmp_path / "alignment one.json"
    output_two = tmp_path / "alignment two.json"
    common = [
        "--script", str(script),
        "--recognition", str(recognition_path),
        "--edit-map", str(edit_map_path),
    ]

    assert main([*common, "--output", str(output_one)]) == 0
    first_summary = json.loads(capsys.readouterr().out)
    assert main([*common, "--output", str(output_two)]) == 0
    capsys.readouterr()

    assert output_one.read_bytes() == output_two.read_bytes()
    payload = json.loads(output_one.read_text(encoding="utf-8"))
    strict_result = read_alignment(output_one)
    assert script.read_bytes() == script_bytes
    assert payload["script"]["source_sha256"] == hashlib.sha256(script_bytes).hexdigest()
    assert payload["script"]["exact_text"] == script_bytes.decode("utf-8")
    assert "um" not in [word["exact_text"] for word in payload["aligned_words"]]
    unmatched_text = [word["text"] for word in payload["unmatched_asr_words"]]
    assert len(unmatched_text) == 1
    assert unmatched_text[0] in {"um", "uh"}
    rejected_text = [word["text"] for word in payload["rejected_asr_evidence"]]
    assert len(rejected_text) == 1
    assert set(unmatched_text + rejected_text) == {"um", "uh"}
    assert payload["aligned_words"][1]["timing_status"] == "interpolated"
    assert payload["aligned_words"][1]["matched_recognition_indices"] == []
    assert payload["aligned_words"][1]["asr_confidence"] is None
    assert payload["aligned_words"][-1]["timing_status"] == "unresolved"
    assert payload["aligned_words"][2]["original_start_sample"] == 4_000
    assert first_summary["output_path"] == str(output_one.resolve())
    assert first_summary["schema_version"] == "alignment.schema.v2"
    assert first_summary["provenance_complete"] is True
    assert first_summary["classified_asr_words"] == 4
    assert first_summary["total_asr_words"] == 4
    assert first_summary["rejected_asr_evidence_count"] == 1
    assert strict_result.schema_version == "alignment.schema.v2"
    assert strict_result.diagnostics.provenance_complete is True

    corrupted = deepcopy(payload)
    corrupted["diagnostics"]["exact_matches"] = 999
    corrupted_path = tmp_path / "corrupted alignment.json"
    corrupted_path.write_text(
        json.dumps(corrupted, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises((AlignmentSerializationError, AlignmentValidationError)):
        read_alignment(corrupted_path)
    assert not list(tmp_path.glob("*.partial.json"))
