from __future__ import annotations

import hashlib
import io
import json
import threading
import urllib.error
from collections import namedtuple
from pathlib import Path

import pytest

from larp_audio_mvp.speech_engine.contracts import EngineReadiness
from larp_audio_mvp.speech_engine.definition import EngineDefinition, EngineFile
from larp_audio_mvp.speech_engine.errors import InsufficientStorageError, SpeechEngineCancelled, SpeechEngineDownloadError, SpeechEngineVerificationError
from larp_audio_mvp.speech_engine.manager import SpeechEngineManager


class Response(io.BytesIO):
    def __init__(self, value: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        super().__init__(value)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def partial(value: bytes, start: int, total: int) -> Response:
    return Response(value, status=206, headers={"Content-Range": f"bytes {start}-{total - 1}/{total}"})


def definition(payload: bytes = b"engine") -> EngineDefinition:
    return EngineDefinition(
        "test", "Test engine", "example/test", "0123456789abcdef", "test-v1",
        (EngineFile("model.bin", len(payload), hashlib.sha256(payload).hexdigest()),),
    )


def test_not_installed_then_download_publish_and_reuse(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    assert manager.status().readiness is EngineReadiness.NOT_INSTALLED
    events = []
    path = manager.prepare(progress=events.append, opener=lambda *_args, **_kwargs: Response(b"engine"))
    assert path == manager.install_path
    assert manager.status().readiness is EngineReadiness.READY
    assert events[-1].downloaded_bytes == 6
    assert not manager.partial_path.exists()
    assert manager.prepare(opener=lambda *_args, **_kwargs: pytest.fail("must reuse")) == path


def test_corruption_and_repair_preserve_explicit_state(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.prepare(opener=lambda *_args, **_kwargs: Response(b"engine"))
    (manager.install_path / "model.bin").write_bytes(b"broken")
    assert manager.status().readiness is EngineReadiness.DAMAGED
    manager.repair(opener=lambda *_args, **_kwargs: Response(b"engine"))
    assert manager.status().readiness is EngineReadiness.READY


def test_cancel_keeps_resumable_partial(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition(b"0123456789"))
    cancel = threading.Event(); cancel.set()
    with pytest.raises(SpeechEngineCancelled):
        manager.prepare(cancel_event=cancel, opener=lambda *_args, **_kwargs: Response(b"0123456789"))
    assert manager.partial_path.exists()
    assert not manager.install_path.exists()


def test_pinned_revision_and_invalid_manifest(tmp_path: Path) -> None:
    value = definition()
    assert len(value.revision) == 16
    manager = SpeechEngineManager(tmp_path, value)
    manager.install_path.mkdir(parents=True)
    (manager.install_path / manager.MANIFEST_NAME).write_text(json.dumps({"revision": "wrong"}))
    with pytest.raises(SpeechEngineVerificationError):
        manager.verify(manager.install_path)


def test_resume_uses_range_and_completes(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition(b"0123456789"))
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"0123")
    seen = {}
    def opener(request, **_kwargs):
        seen["range"] = request.headers.get("Range")
        return partial(b"456789", 4, 10)
    manager.prepare(opener=opener)
    assert seen["range"] == "bytes=4-"
    assert (manager.install_path / "model.bin").read_bytes() == b"0123456789"


def test_retry_after_network_failure(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    with pytest.raises(SpeechEngineDownloadError):
        manager.prepare(opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert manager.prepare(opener=lambda *_args, **_kwargs: Response(b"engine")).is_dir()


def test_insufficient_storage_is_controlled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("shutil.disk_usage", lambda _path: usage(100, 99, 1))
    with pytest.raises(InsufficientStorageError):
        SpeechEngineManager(tmp_path, definition()).prepare(opener=lambda *_args, **_kwargs: Response(b"engine"))


def test_full_size_valid_partial_is_reused_without_request(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"engine")
    manager.prepare(opener=lambda *_args, **_kwargs: pytest.fail("must not request"))
    assert manager.status().readiness is EngineReadiness.READY


def test_full_size_corrupt_partial_restarts_without_end_range(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"broken")
    ranges: list[str | None] = []

    def opener(request, **_kwargs):
        ranges.append(request.headers.get("Range"))
        return Response(b"engine")

    manager.prepare(opener=opener)
    assert ranges == [None]


def test_oversized_partial_restarts_from_zero(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"engine-extra")
    ranges = []

    def opener(request, **_kwargs):
        ranges.append(request.headers.get("Range"))
        return Response(b"engine")

    manager.prepare(opener=opener)
    assert ranges == [None]


def test_http_416_clean_restart_then_success(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"eng")
    calls = 0

    def opener(request, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(request.full_url, 416, "range", {}, None)
        assert request.headers.get("Range") is None
        return Response(b"engine")

    manager.prepare(opener=opener)
    assert calls == 2


def test_repeated_http_416_is_controlled_and_bounded(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"eng")
    calls = 0

    def opener(request, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(request.full_url, 416, "range", {}, None)

    with pytest.raises(SpeechEngineDownloadError):
        manager.prepare(opener=opener)
    assert calls == 2
    assert not (manager.partial_path / "model.bin").exists()


def test_server_ignoring_range_replaces_instead_of_appending(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"eng")
    manager.prepare(opener=lambda *_args, **_kwargs: Response(b"engine", status=200))
    assert (manager.install_path / "model.bin").read_bytes() == b"engine"


@pytest.mark.parametrize(
    "content_range",
    ["invalid", "bytes 2-5/6", "bytes 3-5/999", "bytes 3-2/6"],
)
def test_invalid_content_range_restarts_cleanly(tmp_path: Path, content_range: str) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"eng")
    calls = 0

    def opener(_request, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(b"ine", status=206, headers={"Content-Range": content_range})
        return Response(b"engine")

    manager.prepare(opener=opener)
    assert calls == 2


def test_corrupt_final_download_retries_once_then_succeeds(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    responses = iter((Response(b"broken"), Response(b"engine")))
    manager.prepare(opener=lambda *_args, **_kwargs: next(responses))
    assert manager.status().readiness is EngineReadiness.READY


def test_corrupt_final_download_fails_after_one_retry(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    calls = 0

    def opener(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response(b"broken")

    with pytest.raises(SpeechEngineVerificationError):
        manager.prepare(opener=opener)
    assert calls == 2
    assert not (manager.partial_path / "model.bin").exists()
    assert not manager.install_path.exists()


def test_cancel_during_resumed_stream_keeps_short_partial(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition(b"0123456789"))
    manager.partial_path.mkdir(parents=True)
    (manager.partial_path / "model.bin").write_bytes(b"0123")
    cancel = threading.Event()

    class CancellingResponse(Response):
        def read(self, size=-1):
            value = super().read(2 if size != 0 else size)
            cancel.set()
            return value

    with pytest.raises(SpeechEngineCancelled):
        manager.prepare(
            cancel_event=cancel,
            opener=lambda *_args, **_kwargs: CancellingResponse(
                b"456789", status=206, headers={"Content-Range": "bytes 4-9/10"}
            ),
        )
    candidate = manager.partial_path / "model.bin"
    assert candidate.exists()
    assert candidate.stat().st_size < 10


def test_failed_repair_does_not_damage_previous_install(tmp_path: Path) -> None:
    manager = SpeechEngineManager(tmp_path, definition())
    manager.prepare(opener=lambda *_args, **_kwargs: Response(b"engine"))
    original = (manager.install_path / "model.bin").read_bytes()
    # A forced file-level exercise verifies that publication is never reached.
    manager.partial_path.mkdir(parents=True)
    with pytest.raises(SpeechEngineVerificationError):
        manager._download_file(
            manager.definition.files[0], 0, None, None,
            lambda *_args, **_kwargs: Response(b"broken"),
        )
    assert (manager.install_path / "model.bin").read_bytes() == original
