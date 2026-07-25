"""Explicit synthetic adapters for offline demos and integration tests only."""

from __future__ import annotations

import hashlib
import shutil
import struct
import wave
from dataclasses import replace
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from larp_audio_mvp.alignment import ScriptAlignmentService
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import AudioInfo, AudioLoadResult, EditKind, EditMap, EditSpan, PauseRemovalResult, PauseSegment, RecognitionResult, RecognizedWord, SampleRange
from larp_audio_mvp.subtitles.service import SubtitleGenerationService

from .service import FullProcessingDependencies, FullProcessingService


def write_synthetic_demo_wav(path: Path, frames: int = 192_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48_000)
        # Copyright-free deterministic square wave with one explicit 1 s pause.
        tone = (struct.pack("<h", -1_000) + struct.pack("<h", 1_000))
        before = min(frames, 78_000)
        silence_end = min(frames, 126_000)
        output.writeframes(tone * (before // 2) + (b"\0\0" if before % 2 else b""))
        output.writeframes(b"\0\0" * (silence_end - before))
        remaining = frames - silence_end
        output.writeframes(tone * (remaining // 2) + (b"\0\0" if remaining % 2 else b""))


def _audio_info(path: Path) -> AudioInfo:
    with wave.open(str(path), "rb") as stream:
        samples, rate = stream.getnframes(), stream.getframerate()
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return AudioInfo(path.resolve(), rate, 1, "s16", samples, checksum, "wav", codec_name="pcm_s16le", duration_seconds=Fraction(samples, rate), duration_source="synthetic_demo", bit_depth=16, file_size_bytes=path.stat().st_size, stream_index=0, is_canonical=True)


class SyntheticAudioLoader:
    def __init__(self, workspace: Path, calls: list[str] | None = None) -> None: self.workspace, self.calls = workspace, calls
    def analyze(self, source: Path) -> AudioInfo:
        if self.calls is not None: self.calls.append("analysis")
        return _audio_info(source)
    def canonicalize(self, source_audio: AudioInfo) -> AudioInfo:
        if self.calls is not None: self.calls.append("canonicalization")
        destination = self.workspace / "canonical_audio.wav"; shutil.copyfile(source_audio.source_path, destination)
        return _audio_info(destination)
    def load(self, source: Path) -> AudioLoadResult:
        if self.calls is not None: self.calls.append("ingestion")
        source_audio = self.analyze(source)
        return AudioLoadResult(source_audio, self.canonicalize(source_audio))


class SyntheticPauseDetector:
    def __init__(self, calls: list[str] | None = None) -> None: self.calls = calls
    def detect(self, audio, *, settings):
        if self.calls is not None: self.calls.append("pause_detection")
        return (PauseSegment(78_000, 126_000, audio.sample_rate),)


class SyntheticPauseRemover:
    def __init__(self, calls: list[str] | None = None) -> None: self.calls = calls
    def remove(self, audio, candidates, *, destination: Path):
        if self.calls is not None: self.calls.append("pause_removal")
        edit_map = self.plan(audio, candidates)
        return self.render(audio, edit_map, destination=destination)
    def plan(self, audio, candidates):
        if self.calls is not None: self.calls.append("shortening")
        remove_start, remove_end = 82_800, 121_200
        return EditMap("1", "synthetic-stage-11-v1", audio.sample_rate, audio.total_samples, audio.total_samples - (remove_end - remove_start), audio.sha256, (
            EditSpan(EditKind.KEEP, SampleRange(0, remove_start), SampleRange(0, remove_start), reason="keep before long pause center"),
            EditSpan(EditKind.REMOVE, SampleRange(remove_start, remove_end), reason="shorten deterministic pause center", target_anchor=remove_start, candidate_range=SampleRange(78_000, 126_000), retained_before_samples=4_800, retained_after_samples=4_800),
            EditSpan(EditKind.KEEP, SampleRange(remove_end, audio.total_samples), SampleRange(remove_start, audio.total_samples - (remove_end - remove_start)), reason="keep after long pause center"),
        ), None, warnings=("synthetic_demo_recognition",))
    def render(self, audio, edit_map, *, destination: Path):
        if self.calls is not None: self.calls.append("rendering")
        remove_start, remove_end = 82_800, 121_200
        with wave.open(str(audio.source_path), "rb") as source:
            parameters = source.getparams()
            frames = source.readframes(source.getnframes())
        with wave.open(str(destination), "wb") as output:
            output.setparams(parameters)
            output.writeframes(frames[: remove_start * 2] + frames[remove_end * 2 :])
        cleaned = _audio_info(destination)
        return PauseRemovalResult(destination, replace(edit_map, output_sha256=cleaned.sha256), cleaned)


class SyntheticRecognizer:
    def __init__(self, calls: list[str] | None = None) -> None: self.calls = calls
    def recognize(self, audio, edit_map, *, settings):
        if self.calls is not None: self.calls.append("recognition")
        observed = (
            ("Hello", 12_000, 36_000, 12_000, 36_000),
            ("um", 38_000, 43_000, 38_000, 43_000),
            ("world", 48_000, 72_000, 48_000, 72_000),
            ("Привет", 93_600, 117_600, 132_000, 156_000),
            ("мир", 121_600, 145_600, 160_000, 184_000),
        )
        words = tuple(RecognizedWord(text, audio.sample_rate, original_start, original_end, cleaned_start, cleaned_end, .9) for text, cleaned_start, cleaned_end, original_start, original_end in observed)
        return RecognitionResult("1", "synthetic-local", "tiny", "multi", audio.sample_rate, audio.total_samples, edit_map.source_total_samples, words, (("cleaned_audio_sha256", audio.sha256), ("edit_map_output_sha256", edit_map.output_sha256)))


def create_synthetic_demo_service(calls: list[str] | None = None) -> FullProcessingService:
    calls = calls if calls is not None else []
    real_aligner = ScriptAlignmentService(AlignmentSettings())
    class Aligner:
        def align(self, *args): calls.append("alignment"); return real_aligner.align(*args)
    class Subtitles:
        def generate(self, **kwargs): calls.append("subtitles"); return SubtitleGenerationService().generate(**kwargs)
    dependencies = FullProcessingDependencies(
        audio_loader=lambda workspace: SyntheticAudioLoader(workspace, calls),
        pause_detector=SyntheticPauseDetector(calls), pause_remover=SyntheticPauseRemover(calls), recognizer=SyntheticRecognizer(calls),
        aligner=Aligner(), subtitle_service=Subtitles(), model_preflight=lambda settings: calls.append("preflight"), tool_preflight=lambda: ("ffmpeg synthetic-demo", "ffprobe synthetic-demo"),
    )
    fixed = datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
    ticks = iter(range(10_000))
    return FullProcessingService(
        dependencies,
        clock=lambda: fixed,
        monotonic=lambda: next(ticks) / 1000,
        run_id_generator=lambda: "stage11demo",
    )
