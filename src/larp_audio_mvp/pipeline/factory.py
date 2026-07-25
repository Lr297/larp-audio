"""Composition root for the real local FFmpeg/Faster-Whisper pipeline."""

from __future__ import annotations

from pathlib import Path

from larp_audio_mvp.alignment import ScriptAlignmentService
from larp_audio_mvp.audio import (
    CanonicalWavConverter,
    EditMapBuilder,
    ExecutableResolver,
    FfmpegPauseDetector,
    FfmpegWavRenderer,
    FfprobeAdapter,
    LocalAudioLoader,
    PauseRemovalService,
    PauseShorteningPolicy,
    SubprocessRunner,
)
from larp_audio_mvp.config import (
    AlignmentSettings,
    AudioSettings,
    PauseSettings,
)
from larp_audio_mvp.models import (
    FasterWhisperInference,
    LocalSpeechRecognizer,
    LocalWhisperModelManager,
)
from larp_audio_mvp.subtitles.service import SubtitleGenerationService

from .service import FullProcessingDependencies, FullProcessingService


def create_full_processing_service(
    *,
    audio_settings: AudioSettings,
    pause_settings: PauseSettings,
    alignment_settings: AlignmentSettings,
    ffmpeg_path: Path | None = None,
    ffprobe_path: Path | None = None,
    bundled_tools_directory: Path | None = None,
    model_root: Path | None = None,
    allow_system_tools: bool = True,
) -> FullProcessingService:
    runner = SubprocessRunner()
    tools = ExecutableResolver(
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        bundled_tools_directory=bundled_tools_directory,
        allow_system_path=allow_system_tools,
    ).resolve_all()
    probe = FfprobeAdapter(runner=runner, ffprobe_path=tools.ffprobe, settings=audio_settings)
    converter = CanonicalWavConverter(runner=runner, probe=probe, ffmpeg_path=tools.ffmpeg, settings=audio_settings)
    detector = FfmpegPauseDetector(runner=runner, ffmpeg_path=tools.ffmpeg, subprocess_timeout_seconds=audio_settings.subprocess_timeout_seconds)
    policy = PauseShorteningPolicy(pause_settings)
    renderer = FfmpegWavRenderer(runner=runner, probe=probe, ffmpeg_path=tools.ffmpeg, settings=audio_settings)
    remover = PauseRemovalService(policy=policy, builder=EditMapBuilder(), renderer=renderer)
    manager = LocalWhisperModelManager(model_root=model_root)
    recognizer = LocalSpeechRecognizer(model_manager=manager, backend=FasterWhisperInference())

    def loader(workspace: Path) -> LocalAudioLoader:
        return LocalAudioLoader(probe=probe, converter=converter, work_directory=workspace)

    def tool_preflight() -> tuple[str, str]:
        ffmpeg = runner.run([str(tools.ffmpeg), "-version"], timeout_seconds=audio_settings.subprocess_timeout_seconds)
        ffprobe = runner.run([str(tools.ffprobe), "-version"], timeout_seconds=audio_settings.subprocess_timeout_seconds)
        return ffmpeg.stdout.splitlines()[0][:160], ffprobe.stdout.splitlines()[0][:160]

    return FullProcessingService(
        FullProcessingDependencies(
            audio_loader=loader,
            pause_detector=detector,
            pause_remover=remover,
            recognizer=recognizer,
            aligner=ScriptAlignmentService(alignment_settings),
            subtitle_service=SubtitleGenerationService(),
            model_preflight=manager.resolve,
            tool_preflight=tool_preflight,
        )
    )
