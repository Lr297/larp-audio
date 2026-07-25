"""Pinned production speech-engine definition.

The immutable revision and per-file digests prevent a moving upstream model
from silently changing the local inference engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class EngineDefinition:
    engine_id: str
    display_name: str
    repository: str
    revision: str
    version: str
    files: tuple[EngineFile, ...]
    minimum_free_bytes: int = 1_100_000_000
    supported_languages: tuple[str, ...] = ("multilingual",)
    application_compatibility: str = ">=0.1,<0.2"

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files)

    def url_for(self, item: EngineFile) -> str:
        return (
            f"https://huggingface.co/{self.repository}/resolve/"
            f"{self.revision}/{item.name}?download=true"
        )


RECOMMENDED_ENGINE = EngineDefinition(
    engine_id="faster-whisper-small-multilingual",
    display_name="Recommended multilingual speech engine",
    repository="Systran/faster-whisper-small",
    revision="2ec96c5472da50d38d40c0cfe0602af2e94b4c8a",
    version="small-2ec96c5",
    files=(
        EngineFile("config.json", 2_370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
        EngineFile("model.bin", 483_546_902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
        EngineFile("tokenizer.json", 2_203_239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
        EngineFile("vocabulary.txt", 459_861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
    ),
    minimum_free_bytes=1_100_000_000,
    supported_languages=("multilingual",),
    application_compatibility=">=0.1,<0.2",
)
