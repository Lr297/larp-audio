from __future__ import annotations

import json
from pathlib import Path

from larp_audio_mvp.core.contracts import RecognitionResult, RecognizedWord
from larp_audio_mvp.models import recognition_to_dict, write_recognition_atomic


def test_recognition_serialization_is_exact_stable_and_atomic(tmp_path: Path) -> None:
    result = RecognitionResult(
        schema_version="1",
        backend="faster-whisper",
        model="tiny",
        language="ru",
        sample_rate=48_000,
        duration_samples_cleaned=96_000,
        duration_samples_original=120_000,
        words=(
            RecognizedWord(
                text=" Слово",
                sample_rate=48_000,
                start_sample_cleaned=12_000,
                end_sample_cleaned=24_000,
                start_sample_original=18_000,
                end_sample_original=30_000,
                confidence=0.75,
            ),
        ),
        metadata=(("backend_version", "1.2.1"),),
    )
    destination = tmp_path / "recognition ü.json"

    write_recognition_atomic(result, destination)
    first = destination.read_bytes()
    write_recognition_atomic(result, destination)
    second = destination.read_bytes()
    payload = json.loads(second)

    assert first == second
    assert payload == recognition_to_dict(result)
    assert payload["schema_version"] == "1"
    assert payload["words"][0]["text"] == " Слово"
    assert payload["words"][0]["start_sample_cleaned"] == 12_000
    assert payload["words"][0]["start_sample_original"] == 18_000
    assert payload["words"][0]["start_seconds"]["numerator"] == 1
    assert payload["words"][0]["start_seconds"]["denominator"] == 4
    assert list(tmp_path.glob("*.partial.json")) == []
