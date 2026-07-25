from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from larp_audio_mvp.app.recognize_speech import main as recognize_main
from larp_audio_mvp.audio.serialization import write_edit_map_atomic
from larp_audio_mvp.audio.wav_reader import read_canonical_wav
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.contracts import EditKind, EditMap, EditSpan, SampleRange

pytestmark = [pytest.mark.integration, pytest.mark.stt_integration]


def _local_model() -> tuple[str, Path]:
    root = Path(__file__).resolve().parents[2] / "models"
    required = ("config.json", "model.bin", "tokenizer.json")
    for name in ("tiny", "base", "small"):
        candidate = root / name
        if all((candidate / filename).is_file() for filename in required):
            return name, candidate.resolve()
    pytest.skip(
        "no complete local tiny/base/small Faster-Whisper model under models/"
    )


def _speech_wav(path: Path) -> None:
    if sys.platform != "darwin" or not Path("/usr/bin/say").is_file():
        pytest.skip("synthetic speech fixture currently requires macOS say")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("synthetic speech fixture requires ffmpeg")
    aiff = path.with_suffix(".aiff")
    subprocess.run(
        ["/usr/bin/say", "-v", "Samantha", "-o", str(aiff), "one two three"],
        shell=False,
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(aiff),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        shell=False,
        check=True,
        capture_output=True,
        timeout=30,
    )


def test_real_local_model_cli_produces_monotonic_dual_timeline_words(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model_name, model_path = _local_model()
    cleaned_wav = tmp_path / "cleaned speech ü.wav"
    _speech_wav(cleaned_wav)
    before_hash = hashlib.sha256(cleaned_wav.read_bytes()).hexdigest()
    audio = read_canonical_wav(cleaned_wav, AudioSettings())
    assert audio.total_samples is not None
    source_total = audio.total_samples + 4_800
    edit_map = EditMap(
        schema_version="1",
        policy_version="stt-integration-v1",
        sample_rate=48_000,
        source_total_samples=source_total,
        output_total_samples=audio.total_samples,
        source_sha256="synthetic-source-timeline",
        output_sha256=before_hash,
        spans=(
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(0, 1),
                output_range=SampleRange(0, 1),
                reason="keep",
            ),
            EditSpan(
                kind=EditKind.REMOVE,
                source_range=SampleRange(1, 4_801),
                target_anchor=1,
                candidate_range=SampleRange(0, 4_802),
                retained_before_samples=1,
                retained_after_samples=1,
                reason="synthetic_removed_pause",
            ),
            EditSpan(
                kind=EditKind.KEEP,
                source_range=SampleRange(4_801, source_total),
                output_range=SampleRange(1, audio.total_samples),
                reason="keep",
            ),
        ),
    )
    edit_map_path = tmp_path / "edit_map.json"
    write_edit_map_atomic(edit_map, edit_map_path)
    output = tmp_path / "recognition output"

    exit_code = recognize_main(
        [
            str(cleaned_wav),
            str(edit_map_path),
            "--work-directory",
            str(output),
            "--model",
            model_name,
            "--model-path",
            str(model_path),
            "--language",
            "en",
            "--device",
            "cpu",
            "--compute-type",
            "int8",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    recognition = json.loads(
        (output / "recognition.json").read_text(encoding="utf-8")
    )
    words = recognition["words"]
    assert exit_code == 0
    assert summary["word_count"] > 0
    assert words
    assert all(
        left["start_sample_cleaned"] <= right["start_sample_cleaned"]
        and left["end_sample_cleaned"] <= right["end_sample_cleaned"]
        and left["start_sample_original"] <= right["start_sample_original"]
        and left["end_sample_original"] <= right["end_sample_original"]
        for left, right in zip(words, words[1:])
    )
    assert any(
        word["start_sample_original"] > word["start_sample_cleaned"]
        for word in words
    )
    assert hashlib.sha256(cleaned_wav.read_bytes()).hexdigest() == before_hash
