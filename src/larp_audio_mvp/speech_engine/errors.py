"""Controlled speech-engine failures."""

from larp_audio_mvp.core.errors import ConfigurationError


class SpeechEngineError(ConfigurationError):
    code = "SPEECH_ENGINE_ERROR"


class SpeechEngineDownloadError(SpeechEngineError):
    code = "SPEECH_ENGINE_DOWNLOAD_FAILED"


class SpeechEngineVerificationError(SpeechEngineError):
    code = "SPEECH_ENGINE_VERIFICATION_FAILED"


class SpeechEngineCancelled(SpeechEngineError):
    code = "SPEECH_ENGINE_CANCELLED"


class InsufficientStorageError(SpeechEngineError):
    code = "SPEECH_ENGINE_INSUFFICIENT_STORAGE"
