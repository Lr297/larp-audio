"""Local Faster-Whisper adapter, model preflight, mapping, and serialization."""

from larp_audio_mvp.models.backend import (
    BackendRecognition,
    BackendWord,
    RecognitionBackend,
)
from larp_audio_mvp.models.faster_whisper import FasterWhisperInference
from larp_audio_mvp.models.model_manager import (
    LocalWhisperModel,
    LocalWhisperModelManager,
)
from larp_audio_mvp.models.recognition import (
    LocalSpeechRecognizer,
    RecognitionMapper,
)
from larp_audio_mvp.models.serialization import (
    read_recognition,
    recognition_from_dict,
    recognition_to_dict,
    write_recognition_atomic,
)

__all__ = [
    "BackendRecognition",
    "BackendWord",
    "FasterWhisperInference",
    "LocalSpeechRecognizer",
    "LocalWhisperModel",
    "LocalWhisperModelManager",
    "RecognitionBackend",
    "RecognitionMapper",
    "read_recognition",
    "recognition_from_dict",
    "recognition_to_dict",
    "write_recognition_atomic",
]
