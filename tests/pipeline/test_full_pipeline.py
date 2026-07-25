from __future__ import annotations

import hashlib
import wave
from datetime import UTC, datetime
from pathlib import Path

import pytest

from larp_audio_mvp.alignment import ScriptAlignmentService, read_alignment
from larp_audio_mvp.config import AlignmentSettings, AudioSettings, ModelSettings, PauseSettings, SubtitleSettings
from larp_audio_mvp.core.errors import PipelineCancellationError
from larp_audio_mvp.exports import validate_srt_file
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.artifacts import (
    build_manifest,
    create_package,
    read_processing_report,
    validate_manifest,
    validate_package,
    write_manifest,
    write_processing_report,
)
from larp_audio_mvp.pipeline.contracts import PipelineRunRequest, PipelineStage, ScriptSourceKind
from larp_audio_mvp.pipeline.script_input import create_script_input
from larp_audio_mvp.pipeline.service import FullProcessingDependencies, FullProcessingService
from larp_audio_mvp.subtitles import read_subtitle_document
from larp_audio_mvp.subtitles.service import SubtitleGenerationService

from .fakes import FakeLoader, FakePauseDetector, FakePauseRemover, FakeRecognizer


def write_wav(path: Path, frames: int = 192_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48_000)
        output.writeframes(b"\0\0" * frames)


def make_service(calls: list[str], token: CancellationToken | None = None) -> FullProcessingService:
    alignment = ScriptAlignmentService(AlignmentSettings())

    class TrackedAligner:
        def align(self, script, recognition, edit_map):
            calls.append("alignment")
            return alignment.align(script, recognition, edit_map)

    class TrackedSubtitles:
        def generate(self, **kwargs):
            calls.append("subtitles")
            return SubtitleGenerationService().generate(**kwargs)

    def tracked(name, function):
        def invoke(*args, **kwargs):
            calls.append(name)
            return function(*args, **kwargs)
        return invoke

    deps = FullProcessingDependencies(
        audio_loader=lambda workspace: FakeLoader(workspace, calls),
        pause_detector=FakePauseDetector(calls),
        pause_remover=FakePauseRemover(calls),
        recognizer=FakeRecognizer(calls),
        aligner=TrackedAligner(),
        subtitle_service=TrackedSubtitles(),
        model_preflight=lambda settings: calls.append("preflight"),
        tool_preflight=lambda: ("ffmpeg synthetic", "ffprobe synthetic"),
        report_writer=tracked("reports", write_processing_report),
        manifest_builder=tracked("manifest", build_manifest),
        manifest_writer=write_manifest,
        package_writer=tracked("package", create_package),
        manifest_validator=validate_manifest,
        package_validator=validate_package,
    )
    fixed = datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
    ticks = iter(range(10_000))
    return FullProcessingService(
        deps,
        clock=lambda: fixed,
        monotonic=lambda: next(ticks) / 1000,
        run_id_generator=lambda: "stage11fixed",
    )


def make_request(tmp_path: Path) -> PipelineRunRequest:
    source = tmp_path / "synthetic input.wav"; write_wav(source)
    model = tmp_path / "local-model"; model.mkdir()
    output = tmp_path / "outputs"; output.mkdir()
    script = create_script_input("Hello missing world.\nПривет, мир!", source_kind=ScriptSourceKind.PASTED)
    return PipelineRunRequest(
        source, script, model, output, AudioSettings(),
        PauseSettings(silence_threshold_db=-50, minimum_pause_duration_ms=300, shortening_policy_version="test", minimum_pause_to_shorten_ms=500, target_remaining_pause_ms=200, maximum_removed_per_pause_ms=1000),
        ModelSettings(model_path=model.resolve(), whisper_model="tiny"),
        AlignmentSettings(), SubtitleSettings(minimum_timing_coverage_for_export="0.5"), "0.1.0",
    )


def test_full_fake_pipeline_publishes_nine_valid_artifacts(tmp_path: Path) -> None:
    calls: list[str] = []
    request = make_request(tmp_path)
    source_hash = hashlib.sha256(request.source_audio_path.read_bytes()).hexdigest()
    progress = []
    result = make_service(calls).run(request, progress=progress.append)
    required = {"cleaned_audio.wav", "edit_map.json", "recognition.json", "alignment.json", "subtitle_blocks.json", "subtitles.srt", "processing_report.json", "manifest.json", "voiceover_package.zip"}
    assert {path.name for path in result.final_output_directory.iterdir()} == required
    assert calls == ["preflight", "analysis", "canonicalization", "pause_detection", "shortening", "rendering", "recognition", "alignment", "subtitles", "reports", "manifest", "package"]
    assert [item.stage for item in progress][-1] is PipelineStage.COMPLETE
    assert hashlib.sha256(request.source_audio_path.read_bytes()).hexdigest() == source_hash
    alignment = read_alignment(result.alignment_path)
    assert alignment.script.exact_text == request.script_input.exact_text
    document = read_subtitle_document(result.subtitle_blocks_path)
    validate_srt_file(result.srt_path, document)
    assert "um" not in result.srt_path.read_text(encoding="utf-8")
    assert "missing" in result.srt_path.read_text(encoding="utf-8")
    read_processing_report(result.processing_report_path)
    validate_manifest(result.manifest_path, result.final_output_directory)
    assert len(validate_package(result.package_zip_path)) == 8
    assert not list(request.output_parent_directory.glob(".*.partial"))


def test_cancellation_before_start_publishes_nothing(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    token = CancellationToken(); token.request()
    with pytest.raises(PipelineCancellationError):
        make_service([]).run(request, cancellation=token)
    assert not any(request.output_parent_directory.iterdir())


def test_cancellation_after_recognition_cleans_staging(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    token = CancellationToken()
    service = make_service([])

    def progress(item):
        if item.stage is PipelineStage.RECOGNIZING_SPEECH:
            token.request()

    with pytest.raises(PipelineCancellationError):
        service.run(request, progress=progress, cancellation=token)
    assert not any(request.output_parent_directory.iterdir())


def test_deterministic_outputs_with_fixed_clock_and_run_id(tmp_path: Path) -> None:
    first_request = make_request(tmp_path / "one")
    second_request = make_request(tmp_path / "two")
    first = make_service([]).run(first_request)
    second = make_service([]).run(second_request)
    for name in ("edit_map.json", "recognition.json", "alignment.json", "subtitle_blocks.json", "subtitles.srt"):
        assert (first.final_output_directory / name).read_bytes() == (second.final_output_directory / name).read_bytes()
    report = read_processing_report(first.processing_report_path)
    metrics = dict(report.metrics)
    assert metrics["subtitle_policy_version"] == (
        "conservative-subtitles-v8-syntax-guardrails-45chars-gapless"
    )
    assert "subtitle_segmentation_milliseconds" in metrics
