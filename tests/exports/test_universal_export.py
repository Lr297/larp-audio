from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import (
    ExportCancellationError,
    ExportPublicationError,
    ExportValidationError,
)
from larp_audio_mvp.exports import (
    UniversalExportRequest,
    UniversalExportService,
    safe_export_name,
    subtitle_cues,
    validate_srt_file,
)
from larp_audio_mvp.pipeline import CancellationToken
from tests.pipeline.test_full_pipeline import make_request, make_service


@pytest.fixture
def processed_result(tmp_path: Path):
    return make_service([]).run(make_request(tmp_path / "processed"))


def _request(result, destination: Path, *, name: str = "Тест & Voice's #1"):
    return UniversalExportRequest(
        destination_folder=destination,
        base_name=name,
        cleaned_audio_source=result.cleaned_audio_path,
        cleaned_total_samples=result.summary.cleaned_duration_samples,
        audio_sample_rate=result.summary.sample_rate,
        audio_channel_count=1,
        subtitle_document=result.subtitle_document,
    )


def test_export_publishes_exactly_cleaned_wav_and_gapless_srt(
    processed_result, tmp_path: Path
) -> None:
    destination = tmp_path / "Экспорт с пробелами & O'Brien"
    destination.mkdir()
    original = processed_result.cleaned_audio_path.read_bytes()
    result = UniversalExportService().export(_request(processed_result, destination))
    assert {path.name for path in destination.iterdir()} == {
        "Тест & Voice's #1_audio.wav",
        "Тест & Voice's #1_subtitles.srt",
    }
    assert result.audio_path.read_bytes() == original
    validate_srt_file(result.subtitle_path, processed_result.subtitle_document)
    assert not list(destination.glob("*.xml"))
    assert not list(destination.glob("*.zip"))
    assert not list(destination.glob("*.json"))
    assert not list(destination.glob("script.txt"))
    with wave.open(str(result.audio_path), "rb") as stream:
        assert stream.getframerate() == 48_000
        assert stream.getnchannels() == 1
        assert stream.getnframes() == processed_result.summary.cleaned_duration_samples
        assert stream.getsampwidth() == 2
    cues = subtitle_cues(processed_result.subtitle_document)
    for current, following in zip(cues, cues[1:]):
        assert current.end_milliseconds + 1 == following.start_milliseconds
        assert current.speech_end_sample <= current.display_end_sample
    assert cues[-1].display_end_sample == processed_result.summary.cleaned_duration_samples


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  ElevenLabs voiceover  ", "ElevenLabs voiceover"),
        ("Пример аудио", "Пример аудио"),
        ("A&B's take", "A&B's take"),
        ("bad/name:*?", "bad_name___"),
        ("CON", "LARP Audio"),
    ],
)
def test_export_name_preserves_meaningful_text(raw: str, expected: str) -> None:
    assert safe_export_name(raw) == expected


def test_collision_suffix_is_shared_by_both_files(processed_result, tmp_path: Path) -> None:
    destination = tmp_path / "collision"
    destination.mkdir()
    request = _request(processed_result, destination, name="Voiceover")
    first = UniversalExportService().export(request)
    second = UniversalExportService().export(request)
    assert first.export_name == "Voiceover"
    assert second.export_name == "Voiceover_2"
    assert second.audio_path.name == "Voiceover_2_audio.wav"
    assert second.subtitle_path.name == "Voiceover_2_subtitles.srt"
    assert len(list(destination.iterdir())) == 4


def test_cancelled_export_publishes_nothing(processed_result, tmp_path: Path) -> None:
    destination = tmp_path / "cancelled"
    destination.mkdir()
    token = CancellationToken()
    token.request()
    with pytest.raises(ExportCancellationError):
        UniversalExportService().export(
            _request(processed_result, destination), cancellation=token
        )
    assert not list(destination.iterdir())


def test_mid_export_cancellation_cleans_staging(processed_result, tmp_path: Path) -> None:
    destination = tmp_path / "cancelled-mid"
    destination.mkdir()
    token = CancellationToken()

    def progress(message: str) -> None:
        if message == "Writing subtitles":
            token.request()

    with pytest.raises(ExportCancellationError):
        UniversalExportService().export(
            _request(processed_result, destination),
            progress=progress,
            cancellation=token,
        )
    assert not list(destination.iterdir())


def test_second_file_publication_failure_rolls_back_first(
    processed_result, tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "atomic"
    destination.mkdir()
    real_link = os.link
    calls = 0

    def failing_second_link(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic second publication failure")
        real_link(source, target)

    monkeypatch.setattr("larp_audio_mvp.exports.service.os.link", failing_second_link)
    with pytest.raises(ExportPublicationError):
        UniversalExportService().export(_request(processed_result, destination))
    assert not list(destination.iterdir())


def test_non_directory_destination_is_rejected(processed_result, tmp_path: Path) -> None:
    destination = tmp_path / "not-a-folder"
    destination.write_text("x", encoding="utf-8")
    with pytest.raises(ExportValidationError):
        UniversalExportService().export(_request(processed_result, destination))


def test_source_result_and_semantic_blocks_are_untouched(
    processed_result, tmp_path: Path
) -> None:
    destination = tmp_path / "safe"
    destination.mkdir()
    before_files = {
        path.name: path.read_bytes()
        for path in processed_result.final_output_directory.iterdir()
        if path.is_file()
    }
    before_blocks = tuple(
        (block.source_text_exact, block.cleaned_start_sample, block.cleaned_end_sample)
        for block in processed_result.subtitle_document.blocks
    )
    UniversalExportService().export(_request(processed_result, destination))
    after_files = {
        path.name: path.read_bytes()
        for path in processed_result.final_output_directory.iterdir()
        if path.is_file()
    }
    assert before_files == after_files
    assert before_blocks == tuple(
        (block.source_text_exact, block.cleaned_start_sample, block.cleaned_end_sample)
        for block in processed_result.subtitle_document.blocks
    )


def test_user_files_contain_no_internal_paths(processed_result, tmp_path: Path) -> None:
    destination = tmp_path / "privacy"
    destination.mkdir()
    result = UniversalExportService().export(_request(processed_result, destination))
    srt = result.subtitle_path.read_text(encoding="utf-8")
    assert str(processed_result.final_output_directory) not in srt
    assert str(Path.cwd()) not in srt


def test_export_regenerates_srt_instead_of_copying_stale_pipeline_artifact(
    processed_result, tmp_path: Path
) -> None:
    destination = tmp_path / "fresh-srt"
    destination.mkdir()
    stale = b"1\r\n00:00:00,000 --> 00:00:09,999\r\nSTALE GAP\r\n"
    processed_result.srt_path.write_bytes(stale)
    result = UniversalExportService().export(_request(processed_result, destination))
    assert result.subtitle_path.read_bytes() != stale
    assert b"STALE GAP" not in result.subtitle_path.read_bytes()
    validate_srt_file(result.subtitle_path, processed_result.subtitle_document)
