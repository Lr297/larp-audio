"""Compatibility aliases for the public synthetic Stage 11 demo adapters."""

from larp_audio_mvp.pipeline.demo import (
    SyntheticAudioLoader as FakeLoader,
    SyntheticPauseDetector as FakePauseDetector,
    SyntheticPauseRemover as FakePauseRemover,
    SyntheticRecognizer as FakeRecognizer,
    _audio_info as audio_info,
)
