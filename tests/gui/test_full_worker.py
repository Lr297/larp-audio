from __future__ import annotations

from pathlib import Path

from larp_audio_mvp.core.errors import PipelineCancellationError, PipelineValidationError
from larp_audio_mvp.gui.state import FailureSource, GuiFailure
from larp_audio_mvp.gui.workers import FullProcessingWorker
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.contracts import PipelineCleanupOutcome, PipelineStage
from larp_audio_mvp.pipeline.failures import PipelineRunFailure

from tests.pipeline.test_full_pipeline import make_request


class _Service:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def run(self, request, *, progress, cancellation):
        if self.error is not None:
            raise self.error
        return self.result


def test_full_worker_emits_success_and_always_finishes(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    expected = object()
    worker = FullProcessingWorker(request, lambda _request: _Service(expected), CancellationToken())
    events: list[object] = []
    worker.started.connect(lambda: events.append("started"))
    worker.succeeded.connect(events.append)
    worker.finished.connect(lambda: events.append("finished"))
    worker.run()
    assert events == ["started", expected, "finished"]


def test_full_worker_maps_controlled_failure_and_cancellation(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    failure_worker = FullProcessingWorker(
        request,
        lambda _request: _Service(error=PipelineValidationError("bad input", code="PIPELINE_TEST")),
        CancellationToken(),
    )
    failures: list[GuiFailure] = []
    finished: list[bool] = []
    failure_worker.failed.connect(failures.append)
    failure_worker.finished.connect(lambda: finished.append(True))
    failure_worker.run()
    assert failures[0].error_code == "PIPELINE_TEST"
    assert failures[0].source is FailureSource.FULL_PIPELINE
    assert finished == [True]

    cancelled_worker = FullProcessingWorker(
        request,
        lambda _request: _Service(error=PipelineCancellationError("cancelled", code="PIPELINE_CANCELLED")),
        CancellationToken(),
    )
    cancelled: list[bool] = []
    cancelled_worker.cancelled.connect(lambda: cancelled.append(True))
    cancelled_worker.run()
    assert cancelled == [True]


def test_worker_factory_type_error_is_not_retried_as_zero_argument_factory(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    calls: list[int] = []

    def broken_factory(_request):
        calls.append(1)
        raise TypeError("factory defect")

    worker = FullProcessingWorker(request, broken_factory, CancellationToken())
    failures: list[GuiFailure] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert calls == [1]
    assert failures[0].error_code == "GUI_PIPELINE_INTERNAL"


def test_full_worker_reports_primary_and_secondary_cleanup_failure(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    primary = PipelineValidationError("recognition failed", code="PRIMARY_FAILURE")
    cleanup = PipelineCleanupOutcome(
        attempted=True,
        completed=False,
        staging_path_safe_display=".run.partial",
        residual_workspace_exists=True,
        error_code="PIPELINE_CLEANUP_FAILED",
        message="Temporary workspace cleanup did not complete.",
        manual_cleanup_may_be_required=True,
        residual_workspace_path=tmp_path / ".run.partial",
    )
    error = PipelineRunFailure(
        primary,
        failed_stage=PipelineStage.RECOGNIZING_SPEECH,
        cleanup_outcome=cleanup,
    )
    worker = FullProcessingWorker(
        request, lambda _request: _Service(error=error), CancellationToken()
    )
    failures: list[GuiFailure] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert failures[0].error_code == "PRIMARY_FAILURE"
    assert failures[0].cleanup_outcome == cleanup
    assert failures[0].related_path == cleanup.residual_workspace_path
    assert "completed: no" in failures[0].details
