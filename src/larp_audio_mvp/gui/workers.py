"""QThread worker boundary for the synchronous subtitle backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.logging import get_logger
from larp_audio_mvp.subtitles import read_subtitle_document
from larp_audio_mvp.subtitles.service import SubtitleGenerationService

from .state import AudioPreflightRequest, AudioPreflightResult, FailureSource, GeneratedResult, GuiFailure
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.contracts import PipelineRunRequest
from larp_audio_mvp.pipeline.contracts import PipelineRunResult
from larp_audio_mvp.pipeline.failures import PipelineCancelledFailure, PipelineRunFailure
from larp_audio_mvp.exports import UniversalExportRequest, UniversalExportService
from larp_audio_mvp.core.errors import ExportCancellationError

LOGGER = get_logger("gui.worker")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    alignment_path: Path
    output_directory: Path
    settings: SubtitleSettings

    @property
    def blocks_path(self) -> Path:
        return self.output_directory / "subtitle_blocks.json"

    @property
    def srt_path(self) -> Path:
        return self.output_directory / "subtitles.srt"


class AudioPreflightWorker(QObject):
    """Read-only ffprobe task used immediately after selecting local audio."""

    completed = Signal(object)
    finished = Signal()

    def __init__(self, request: AudioPreflightRequest, probe_factory: object) -> None:
        super().__init__()
        self._request = request
        self._probe_factory = probe_factory

    @Slot()
    def run(self) -> None:
        try:
            factory = self._probe_factory
            probe = factory() if callable(factory) else factory
            metadata = probe.probe(self._request.source_path)
            self.completed.emit(AudioPreflightResult(
                self._request.request_id,
                self._request.source_path,
                self._request.normalized_path_identity,
                metadata,
            ))
        except ProjectError as exc:
            self.completed.emit(AudioPreflightResult(
                self._request.request_id,
                self._request.source_path,
                self._request.normalized_path_identity,
                None,
                exc.code,
                str(exc),
            ))
        except Exception:
            LOGGER.exception("unexpected audio preflight failure")
            self.completed.emit(AudioPreflightResult(
                self._request.request_id,
                self._request.source_path,
                self._request.normalized_path_identity,
                None,
                "GUI_AUDIO_PREFLIGHT_FAILED",
                "The selected audio could not be inspected.",
            ))
        finally:
            self.finished.emit()


class PreviewPreparationWorker(QObject):
    """Run hashing and package/cross-artifact checks away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, result: PipelineRunResult, service_factory: object) -> None:
        super().__init__()
        self._result = result
        self._service_factory = service_factory

    @Slot()
    def run(self) -> None:
        try:
            factory = self._service_factory
            service = factory() if callable(factory) else factory
            self.succeeded.emit(service.prepare(self._result))
        except ProjectError as exc:
            self.failed.emit(GuiFailure("Preview unavailable", str(exc), exc.code, source=FailureSource.INTERNAL))
        except Exception:
            LOGGER.exception("unexpected preview preparation failure")
            self.failed.emit(GuiFailure("Preview unavailable", "The completed run could not be prepared for preview.", "PREVIEW_PREPARATION_FAILED", is_unexpected=True, source=FailureSource.INTERNAL))
        finally:
            self.finished.emit()


class UniversalExportWorker(QObject):
    """Widget-free cooperative two-file export worker."""

    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        request: UniversalExportRequest,
        service: UniversalExportService,
        token: CancellationToken,
    ) -> None:
        super().__init__()
        self._request = request
        self._service = service
        self._token = token

    def request_cancellation(self) -> bool:
        return self._token.request()

    @Slot()
    def run(self) -> None:
        try:
            result = self._service.export(
                self._request,
                progress=self.progress.emit,
                cancellation=self._token,
            )
            self.succeeded.emit(result)
        except ExportCancellationError:
            self.cancelled.emit()
        except ProjectError as exc:
            self.failed.emit((exc.code, str(exc)))
        except Exception:
            LOGGER.exception("unexpected universal export failure")
            self.failed.emit(("EXPORT_INTERNAL_ERROR", "The export could not be completed."))
        finally:
            self.finished.emit()


class SubtitleGenerationWorker(QObject):
    started = Signal()
    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        request: GenerationRequest,
        service: SubtitleGenerationService,
    ) -> None:
        super().__init__()
        self._request = request
        self._service = service

    @Slot()
    def run(self) -> None:
        self.started.emit()
        try:
            self.progress.emit("Validating alignment")
            self.progress.emit("Preparing outputs")
            self.progress.emit("Building subtitle blocks and writing artifacts")
            summary = self._service.generate(
                alignment_path=self._request.alignment_path,
                blocks_output=self._request.blocks_path,
                srt_output=self._request.srt_path,
                settings=self._request.settings,
            )
            self.progress.emit("Validating results")
            document = read_subtitle_document(summary.subtitle_blocks_path)
            self.progress.emit("Complete")
            self.succeeded.emit(GeneratedResult(summary=summary, document=document))
        except ProjectError as exc:
            LOGGER.warning("subtitle GUI job failed code=%s", exc.code)
            self.failed.emit(
                GuiFailure(
                    title="Subtitle generation failed",
                    message=str(exc),
                    error_code=exc.code,
                    source=FailureSource.SUBTITLE_GENERATION,
                )
            )
        except Exception:
            LOGGER.exception("unexpected subtitle GUI worker failure")
            self.failed.emit(
                GuiFailure(
                    title="Unexpected internal error",
                    message="The operation could not be completed. Try again or check the logs.",
                    error_code="GUI_INTERNAL_ERROR",
                    is_unexpected=True,
                    source=FailureSource.SUBTITLE_GENERATION,
                )
            )
        finally:
            self.finished.emit()


class FullProcessingWorker(QObject):
    """Widget-free QThread boundary for the complete local pipeline."""

    started = Signal()
    progress = Signal(object)
    cancellation_requested = Signal()
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)
    finished = Signal()

    def __init__(self, request: PipelineRunRequest, service_factory: object, token: CancellationToken) -> None:
        super().__init__()
        self._request = request
        self._service_factory = service_factory
        self._token = token

    def request_cancellation(self) -> bool:
        accepted = self._token.request()
        if accepted:
            self.cancellation_requested.emit()
        return accepted

    @Slot()
    def run(self) -> None:
        from larp_audio_mvp.core.errors import PipelineCancellationError

        self.started.emit()
        service_created = False
        try:
            factory = self._service_factory
            service = factory(self._request) if callable(factory) else factory
            service_created = True
            result = service.run(self._request, progress=self.progress.emit, cancellation=self._token)
            self.succeeded.emit(result)
        except PipelineCancelledFailure as exc:
            if exc.cleanup_outcome.completed:
                self.cancelled.emit(exc.cleanup_outcome)
            else:
                self.failed.emit(_pipeline_failure(exc, title="Processing cancelled; cleanup incomplete"))
        except PipelineRunFailure as exc:
            self.failed.emit(_pipeline_failure(exc, title="Audio processing failed"))
        except PipelineCancellationError:
            self.cancelled.emit(None)
        except ProjectError as exc:
            LOGGER.warning("full pipeline GUI job failed code=%s", exc.code)
            self.failed.emit(
                GuiFailure(
                    title="Audio processing failed",
                    message=str(exc),
                    error_code=exc.code,
                    details=(
                        "Cleanup status is unavailable."
                        if service_created
                        else "No processing workspace was created."
                    ),
                    source=FailureSource.FULL_PIPELINE,
                )
            )
        except Exception:
            LOGGER.exception("unexpected full pipeline worker failure")
            self.failed.emit(
                GuiFailure(
                    title="Unexpected processing error",
                    message="The local processing workflow could not be completed.",
                    error_code="GUI_PIPELINE_INTERNAL",
                    details=(
                        "Cleanup status is unavailable."
                        if service_created
                        else "No processing workspace was created."
                    ),
                    is_unexpected=True,
                    source=FailureSource.INTERNAL,
                )
            )
        finally:
            self.finished.emit()


def _pipeline_failure(exc: PipelineRunFailure | PipelineCancelledFailure, *, title: str) -> GuiFailure:
    cleanup = exc.cleanup_outcome
    details = (
        f"Failed stage: {exc.failed_stage.value}. "
        f"Cleanup attempted: {'yes' if cleanup.attempted else 'no'}; "
        f"completed: {'yes' if cleanup.completed else 'no'}; "
        f"residual workspace: {'yes' if cleanup.residual_workspace_exists else 'no'}."
    )
    return GuiFailure(
        title=title,
        message=str(exc.primary_error),
        error_code=exc.code,
        details=details,
        related_path=cleanup.residual_workspace_path,
        source=FailureSource.FULL_PIPELINE,
        cleanup_outcome=cleanup,
    )
