"""Application-managed local Faster-Whisper engine."""

from .contracts import EngineProgress, EngineReadiness, EngineStatus
from .definition import RECOMMENDED_ENGINE, EngineDefinition, EngineFile
from .manager import SpeechEngineManager

__all__ = [
    "EngineDefinition",
    "EngineFile",
    "EngineProgress",
    "EngineReadiness",
    "EngineStatus",
    "RECOMMENDED_ENGINE",
    "SpeechEngineManager",
]
