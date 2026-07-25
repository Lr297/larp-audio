"""Package-level smoke tests."""

from __future__ import annotations

import importlib
import pkgutil

import larp_audio_mvp


def test_all_project_modules_import() -> None:
    module_names = [
        module.name
        for module in pkgutil.walk_packages(
            larp_audio_mvp.__path__, prefix=f"{larp_audio_mvp.__name__}."
        )
    ]

    assert module_names
    for module_name in module_names:
        importlib.import_module(module_name)


def test_pipeline_interfaces_are_importable() -> None:
    from larp_audio_mvp.pipeline import (
        AudioLoader,
        Exporter,
        PauseDetector,
        PauseRemover,
        SpeechRecognizer,
        SubtitleChunker,
        WordAligner,
    )

    assert all(
        interface is not None
        for interface in (
            AudioLoader,
            PauseDetector,
            PauseRemover,
            SpeechRecognizer,
            WordAligner,
            SubtitleChunker,
            Exporter,
        )
    )

