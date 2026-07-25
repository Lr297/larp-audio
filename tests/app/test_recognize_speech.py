from __future__ import annotations

import hashlib
import wave
from pathlib import Path

import pytest

from larp_audio_mvp.app.recognize_speech import main
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.core.contracts import EditKind, EditMap, EditSpan, SampleRange


def test_cli_reports_missing_local_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    audio = tmp_path / "cleaned ü.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\0\0" * 4_800)
    target_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    edit_map = EditMap(
        schema_version="1",
        policy_version="identity-v1",
        sample_rate=48_000,
        source_total_samples=4_800,
        output_total_samples=4_800,
        source_sha256=target_hash,
        output_sha256=target_hash,
        spans=(
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(0, 4_800),
                output_range=SampleRange(0, 4_800),
                reason="identity",
            ),
        ),
    )
    edit_map_path = tmp_path / "edit_map.json"
    write_edit_map_atomic(edit_map, edit_map_path)

    exit_code = main(
        [
            str(audio),
            str(edit_map_path),
            "--work-directory",
            str(tmp_path / "output"),
            "--model",
            "tiny",
            "--model-root",
            str(tmp_path / "missing models"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error [STT_MODEL_NOT_FOUND]" in captured.err
    assert not (tmp_path / "output" / "recognition.json").exists()
