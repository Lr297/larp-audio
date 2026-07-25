"""Transactional download, verification and reuse of the local STT engine."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import certifi

from .contracts import EngineProgress, EngineReadiness, EngineStatus
from .definition import RECOMMENDED_ENGINE, EngineDefinition, EngineFile
from .errors import (
    InsufficientStorageError,
    SpeechEngineCancelled,
    SpeechEngineDownloadError,
    SpeechEngineVerificationError,
)

ProgressCallback = Callable[[EngineProgress], None]


class _CleanRestartRequired(Exception):
    """Internal bounded-recovery signal; never crosses the manager boundary."""


class SpeechEngineManager:
    """Own one pinned engine below an injected application-data directory."""

    MANIFEST_NAME = "engine-manifest.json"
    MAX_AUTOMATIC_RESTARTS_PER_FILE = 1

    def __init__(self, application_data: Path, definition: EngineDefinition = RECOMMENDED_ENGINE) -> None:
        self.application_data = Path(application_data)
        self.definition = definition
        self.engines_root = self.application_data / "speech-engines"
        self.install_path = self.engines_root / definition.version
        self.partial_path = self.engines_root / f".{definition.version}.partial"

    def status(self) -> EngineStatus:
        if not self.install_path.exists():
            return EngineStatus(EngineReadiness.NOT_INSTALLED)
        try:
            self.verify(self.install_path)
        except SpeechEngineVerificationError as exc:
            return EngineStatus(EngineReadiness.DAMAGED, self.install_path, detail=str(exc))
        return EngineStatus(EngineReadiness.READY, self.install_path, self.definition.version)

    def verify(self, directory: Path) -> None:
        directory = Path(directory)
        manifest_path = directory / self.MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SpeechEngineVerificationError("Speech engine manifest is missing or unreadable.") from exc
        if manifest.get("engine_id") != self.definition.engine_id or manifest.get("revision") != self.definition.revision:
            raise SpeechEngineVerificationError("Speech engine version does not match the pinned application engine.")
        for item in self.definition.files:
            path = directory / item.name
            if not path.is_file() or path.stat().st_size != item.size:
                raise SpeechEngineVerificationError(f"Speech engine file is missing or has the wrong size: {item.name}")
            if self._sha256(path) != item.sha256:
                raise SpeechEngineVerificationError(f"Speech engine file failed integrity verification: {item.name}")

    def prepare(
        self,
        *,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
        opener: Callable[..., object] | None = None,
    ) -> Path:
        current = self.status()
        if current.readiness is EngineReadiness.READY and current.model_path is not None:
            return current.model_path
        self.engines_root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.engines_root).free
        required = max(
            self.definition.minimum_free_bytes,
            self.definition.total_bytes * 2 + 128 * 1024 * 1024,
        )
        if free < required:
            raise InsufficientStorageError(
                f"Not enough free storage to prepare the speech engine; {required} bytes are required."
            )
        self.partial_path.mkdir(parents=True, exist_ok=True)
        completed = 0
        for item in self.definition.files:
            completed += self._download_file(item, completed, progress, cancel_event, opener)
        self._write_manifest(self.partial_path)
        self.verify(self.partial_path)
        backup = self.engines_root / f".{self.definition.version}.previous"
        if backup.exists():
            shutil.rmtree(backup)
        if self.install_path.exists():
            os.replace(self.install_path, backup)
        try:
            os.replace(self.partial_path, self.install_path)
        except OSError:
            if backup.exists() and not self.install_path.exists():
                os.replace(backup, self.install_path)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return self.install_path

    def repair(self, **kwargs: object) -> Path:
        return self.prepare(**kwargs)  # type: ignore[arg-type]

    def remove(self) -> None:
        if self.install_path.exists():
            shutil.rmtree(self.install_path)
        if self.partial_path.exists():
            shutil.rmtree(self.partial_path)

    def cleanup_abandoned_download(self) -> None:
        if not self.partial_path.exists():
            return
        valid_names = {item.name for item in self.definition.files}
        for child in self.partial_path.iterdir():
            if child.name not in valid_names and child.name != self.MANIFEST_NAME:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

    def _download_file(
        self,
        item: EngineFile,
        completed_before: int,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
        opener: Callable[..., object] | None,
    ) -> int:
        target = self.partial_path / item.name
        restarts = 0
        while True:
            existing = target.stat().st_size if target.exists() else 0
            if existing > item.size:
                target.unlink()
                existing = 0
            if existing == item.size:
                if self._sha256(target) == item.sha256:
                    self._emit(progress, "verifying", completed_before + item.size, item.name)
                    return item.size
                target.unlink()
                existing = 0
            try:
                self._download_attempt(
                    item,
                    target,
                    existing,
                    completed_before,
                    progress,
                    cancel_event,
                    opener,
                )
            except _CleanRestartRequired as exc:
                target.unlink(missing_ok=True)
                if restarts >= self.MAX_AUTOMATIC_RESTARTS_PER_FILE:
                    raise SpeechEngineDownloadError(
                        f"The speech engine server could not provide a valid download for {item.name}. Retry later."
                    ) from exc
                restarts += 1
                continue
            if target.stat().st_size == item.size and self._sha256(target) == item.sha256:
                self._emit(progress, "verifying", completed_before + item.size, item.name)
                return item.size
            target.unlink(missing_ok=True)
            if restarts >= self.MAX_AUTOMATIC_RESTARTS_PER_FILE:
                raise SpeechEngineVerificationError(
                    f"Downloaded speech engine file is corrupt after a clean retry: {item.name}"
                )
            restarts += 1

    def _download_attempt(
        self,
        item: EngineFile,
        target: Path,
        existing: int,
        completed_before: int,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
        opener: Callable[..., object] | None,
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise SpeechEngineCancelled("Speech engine setup was cancelled. You can resume later.")
        headers = {"User-Agent": "LARP-Audio/0.1", "Accept-Encoding": "identity"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(self.definition.url_for(item), headers=headers)
        try:
            response = (
                opener(request, timeout=30)
                if opener is not None
                else urllib.request.urlopen(
                    request,
                    timeout=30,
                    context=ssl.create_default_context(cafile=certifi.where()),
                )
            )
            status = getattr(response, "status", 200)
            if existing and status == 206:
                self._validate_content_range(response, existing, item.size)
            elif existing and status == 200:
                target.unlink(missing_ok=True)
                existing = 0
            elif existing:
                raise _CleanRestartRequired(f"unexpected range response status {status}")
            elif status not in (200, 206):
                raise _CleanRestartRequired(f"unexpected response status {status}")
            elif status == 206:
                self._validate_content_range(response, 0, item.size)
            mode = "ab" if existing else "wb"
            with response, target.open(mode) as output:
                downloaded = existing
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise SpeechEngineCancelled("Speech engine setup was cancelled. You can resume later.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    self._emit(progress, "downloading", completed_before + downloaded, item.name)
                output.flush()
                os.fsync(output.fileno())
        except SpeechEngineCancelled:
            raise
        except _CleanRestartRequired:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 416:
                raise _CleanRestartRequired("server rejected the requested byte range") from exc
            raise SpeechEngineDownloadError(
                "The speech engine download could not be completed. Check the connection and retry."
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise SpeechEngineDownloadError(
                "The speech engine download could not be completed. Check the connection and retry."
            ) from exc

    @staticmethod
    def _validate_content_range(response: object, expected_start: int, expected_total: int) -> None:
        headers = getattr(response, "headers", None)
        value = headers.get("Content-Range") if headers is not None else None
        if not isinstance(value, str) or not value.startswith("bytes "):
            raise _CleanRestartRequired("missing or malformed Content-Range")
        try:
            bounds, total_text = value[6:].split("/", 1)
            start_text, end_text = bounds.split("-", 1)
            start, end, total = int(start_text), int(end_text), int(total_text)
        except (TypeError, ValueError) as exc:
            raise _CleanRestartRequired("malformed Content-Range") from exc
        if start != expected_start or total != expected_total or end < start or end >= total:
            raise _CleanRestartRequired("Content-Range does not match the local candidate")

    def _emit(self, callback: ProgressCallback | None, stage: str, completed: int, filename: str) -> None:
        if callback is not None:
            callback(EngineProgress(stage, completed, self.definition.total_bytes, filename))

    def _write_manifest(self, directory: Path) -> None:
        payload = {
            "schema_version": "speech-engine-manifest.v1",
            "engine_id": self.definition.engine_id,
            "display_name": self.definition.display_name,
            "repository": self.definition.repository,
            "revision": self.definition.revision,
            "version": self.definition.version,
            "files": [item.__dict__ if hasattr(item, "__dict__") else {"name": item.name, "size": item.size, "sha256": item.sha256} for item in self.definition.files],
        }
        temporary = directory / f".{self.MANIFEST_NAME}.partial"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, directory / self.MANIFEST_NAME)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
