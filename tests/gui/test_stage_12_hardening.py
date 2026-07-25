from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from larp_audio_mvp.core.errors import PipelineValidationError
from larp_audio_mvp.gui.controller import GuiController
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.state import AudioPreflightRequest, AudioPreflightResult
from larp_audio_mvp.gui.workers import FullProcessingWorker
from larp_audio_mvp.pipeline import CancellationToken
from tests.pipeline.fakes import audio_info
from tests.pipeline.test_full_pipeline import make_request, write_wav


def _request(path: Path, serial: int) -> AudioPreflightRequest:
    identity = str(path.resolve())
    return AudioPreflightRequest(f"request-{serial}", path, identity, serial)


@pytest.mark.parametrize("order", ((0, 1), (1, 0)))
def test_only_current_audio_preflight_result_is_applied(tmp_path: Path, order: tuple[int, int]) -> None:
    paths = (tmp_path / "A.wav", tmp_path / "B.wav")
    for path in paths:
        write_wav(path)
    controller = GuiController()
    requests = tuple(_request(path, index) for index, path in enumerate(paths))
    assert controller.begin_audio_preflight(requests[0])
    assert controller.begin_audio_preflight(requests[1])
    results = tuple(
        AudioPreflightResult(item.request_id, item.source_path, item.normalized_path_identity, audio_info(item.source_path))
        for item in requests
    )
    applied = [controller.apply_audio_preflight_result(results[index]) for index in order]
    assert applied[order.index(1)] is True
    assert controller.state.source_audio_path == paths[1]
    assert controller.state.audio_preflight_metadata == results[1].metadata
    assert controller.state.audio_preflight_ready is True
    assert controller.state.active_failure is None


def test_stale_failure_and_success_cannot_change_current_broken_selection(tmp_path: Path) -> None:
    paths = tuple(tmp_path / f"{name}.wav" for name in ("A", "B", "C"))
    for path in paths:
        write_wav(path)
    controller = GuiController()
    requests = tuple(_request(path, index) for index, path in enumerate(paths))
    for request in requests:
        assert controller.begin_audio_preflight(request)
    stale_failure = AudioPreflightResult(requests[0].request_id, paths[0], requests[0].normalized_path_identity, None, "BROKEN", "old failure")
    stale_success = AudioPreflightResult(requests[1].request_id, paths[1], requests[1].normalized_path_identity, audio_info(paths[1]))
    assert not controller.apply_audio_preflight_result(stale_failure)
    assert not controller.apply_audio_preflight_result(stale_success)
    assert controller.state.source_audio_path == paths[2]
    assert controller.state.audio_preflight_ready is False
    assert controller.state.audio_preflight_metadata is None
    assert controller.state.active_failure is None


def test_script_editor_is_resizable_and_available_at_supported_sizes(qapp, tmp_path: Path) -> None:
    window = MainWindow(settings=QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    window.show()
    for width, height in ((1100, 760), (1280, 900), (1440, 900)):
        window.resize(width, height)
        qapp.processEvents()
        assert window.script_editor.minimumHeight() >= 90
        assert window.script_editor.isVisible()
        assert window.load_script_button.isVisible()
        assert window.clear_script_button.isVisible()
        assert window.script_counter.isVisible()
        assert window.script_input_splitter.handleWidth() > 0
    window.close()


@pytest.mark.parametrize(
    ("factory", "expected"),
    (
        (lambda _request: (_ for _ in ()).throw(PipelineValidationError("factory", code="FACTORY")), "No processing workspace was created."),
        (lambda _request: type("Service", (), {"run": lambda self, *a, **k: (_ for _ in ()).throw(PipelineValidationError("run", code="RUN"))})(), "Cleanup status is unavailable."),
    ),
)
def test_worker_never_invents_cleanup_status(tmp_path: Path, factory, expected: str) -> None:
    worker = FullProcessingWorker(make_request(tmp_path), factory, CancellationToken())
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert len(failures) == 1
    assert failures[0].details == expected
    assert "was cleaned" not in failures[0].details
