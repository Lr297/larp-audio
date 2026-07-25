"""Unified GUI orchestration for full and alignment-only workflows."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from larp_audio_mvp.alignment import read_alignment
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.errors import ProjectError
from larp_audio_mvp.core.contracts import ScriptTokenKind
from larp_audio_mvp.core.logging import get_logger
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.contracts import PipelineCleanupOutcome, PipelineProgress, PipelineRunRequest, PipelineRunResult, ScriptInput
from larp_audio_mvp.subtitles.service import SubtitleGenerationService
from larp_audio_mvp.subtitles.syntax import LocalEnglishSyntaxAnalyzer

from .state import AudioPreflightRequest, AudioPreflightResult, FailureSource, GeneratedResult, GuiFailure, GuiPhase, GuiState, summarize_alignment, validate_gui_state
from .workers import FullProcessingWorker, GenerationRequest, SubtitleGenerationWorker

LOGGER = get_logger("gui.controller")


class TaskLifecycle(StrEnum):
    IDLE = "idle"
    CREATED = "created"
    RUNNING = "running"
    BACKEND_SUCCEEDED = "backend_succeeded"
    BACKEND_FAILED = "backend_failed"
    FINISHING = "finishing"


WorkerFactory = Callable[[GenerationRequest, object], SubtitleGenerationWorker]


class GuiController(QObject):
    state_changed = Signal(object)

    def __init__(self, *, service_factory: object | None = None, worker_factory: WorkerFactory | None = None, full_service_factory: object | None = None, full_worker_factory: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = GuiState()
        self._service_factory = service_factory or SubtitleGenerationService
        self._worker_factory = worker_factory or SubtitleGenerationWorker
        self._full_service_factory = full_service_factory
        self._full_worker_factory = full_worker_factory or FullProcessingWorker
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._task_lifecycle = TaskLifecycle.IDLE
        self._pending_result: GeneratedResult | PipelineRunResult | None = None
        self._pending_failure: GuiFailure | None = None
        self._pending_cancelled = False
        self._pending_cleanup: PipelineCleanupOutcome | None = None
        self._phase_before_task = GuiPhase.READY
        self._cancellation_token: CancellationToken | None = None
        self._workflow = "subtitle"

    @property
    def state(self) -> GuiState: return self._state

    @property
    def task_lifecycle(self) -> TaskLifecycle: return self._task_lifecycle

    @property
    def has_pending_outcome(self) -> bool:
        return self._pending_result is not None or self._pending_failure is not None or self._pending_cancelled

    def _publish(self, state: GuiState) -> None:
        validate_gui_state(state)
        self._state = state
        self.state_changed.emit(state)

    def report_failure(self, failure: GuiFailure) -> None:
        self._publish(replace(self._state, active_failure=failure))

    def dismiss_failure(self) -> None:
        if self._state.active_failure is not None: self._publish(replace(self._state, active_failure=None))

    def dismiss_error(self) -> None: self.dismiss_failure()

    def set_progress_message(self, message: str) -> None: self._publish(replace(self._state, progress_message=message))

    def _busy_failure(self, action: str) -> GuiFailure:
        return GuiFailure("Operation still running", f"Wait for processing to finish before {action}.", "GUI_TASK_ACTIVE", details=f"Task lifecycle: {self._task_lifecycle.value}", source=FailureSource.INTERNAL)

    def _stable_input_phase(self, state: GuiState) -> GuiState:
        if state.source_audio_path is None and state.alignment is not None:
            return replace(state, phase=GuiPhase.SUCCESS if state.generated_result else GuiPhase.READY)
        complete = all((state.source_audio_path, state.script_input, state.local_model_path, state.output_directory))
        return replace(
            state,
            phase=GuiPhase.INPUT_READY if complete else GuiPhase.EMPTY,
            progress_message=(
                "Inputs are ready. Review local settings and create the package."
                if complete
                else "Select audio, exact script, local model, and output folder."
            ),
        )

    def set_output_directory(self, path: Path | None) -> bool:
        if self._state.task_active:
            self.report_failure(self._busy_failure("changing the output folder")); return False
        self._publish(self._stable_input_phase(replace(self._state, output_directory=path, active_failure=None)))
        return True

    def set_source_audio(self, path: Path | None) -> None:
        if self._state.task_active: self.report_failure(self._busy_failure("changing the audio input")); return
        self._publish(self._stable_input_phase(replace(
            self._state,
            source_audio_path=path,
            audio_preflight_request=None,
            audio_preflight_metadata=None,
            audio_preflight_ready=None,
            pipeline_result=None,
            active_failure=None,
        )))

    def reset_project_inputs(self) -> bool:
        """Clear run-specific state while retaining global model/output preferences."""
        if self._state.task_active:
            return False
        self._publish(replace(
            self._state,
            phase=GuiPhase.EMPTY,
            source_audio_path=None,
            audio_preflight_request=None,
            audio_preflight_metadata=None,
            audio_preflight_ready=None,
            script_input=None,
            alignment_path=None,
            alignment=None,
            alignment_summary=None,
            generated_result=None,
            pipeline_result=None,
            pipeline_progress=None,
            completed_pipeline_stages=(),
            active_failure=None,
            warnings=(),
            progress_message="Upload audio and add the exact original script.",
            task_active=False,
        ))
        return True

    def begin_audio_preflight(self, request: AudioPreflightRequest) -> bool:
        if self._state.task_active:
            self.report_failure(self._busy_failure("checking another audio input"))
            return False
        self._publish(replace(
            self._state,
            source_audio_path=request.source_path,
            audio_preflight_request=request,
            audio_preflight_metadata=None,
            audio_preflight_ready=False,
            pipeline_result=None,
            active_failure=None,
            phase=GuiPhase.PREFLIGHTING,
            progress_message="Inspecting selected audio metadata…",
        ))
        return True

    def apply_audio_preflight_result(self, result: AudioPreflightResult) -> bool:
        current = self._state.audio_preflight_request
        if (
            current is None
            or result.request_id != current.request_id
            or result.normalized_path_identity != current.normalized_path_identity
        ):
            LOGGER.info("ignored stale audio preflight request_id=%s", result.request_id)
            return False
        if result.succeeded:
            next_state = replace(
                self._state,
                audio_preflight_metadata=result.metadata,
                audio_preflight_ready=True,
                active_failure=None,
            )
        else:
            next_state = replace(
                self._state,
                audio_preflight_metadata=None,
                audio_preflight_ready=False,
                active_failure=GuiFailure(
                    "Audio preflight failed",
                    result.error_message or "The selected audio could not be inspected.",
                    result.error_code or "GUI_AUDIO_PREFLIGHT_FAILED",
                    related_path=result.source_path,
                    source=FailureSource.SETTINGS_VALIDATION,
                ),
            )
        self._publish(self._stable_input_phase(next_state))
        return True

    def set_script_input(self, script: ScriptInput | None) -> None:
        if self._state.task_active: self.report_failure(self._busy_failure("editing the script")); return
        self._publish(self._stable_input_phase(replace(self._state, script_input=script, pipeline_result=None, active_failure=None)))

    def set_local_model(self, path: Path | None) -> None:
        if self._state.task_active: self.report_failure(self._busy_failure("changing the local model")); return
        self._publish(self._stable_input_phase(replace(self._state, local_model_path=path, pipeline_result=None, active_failure=None)))

    def load_alignment(self, path: Path) -> bool:
        if self._state.task_active:
            self.report_failure(self._busy_failure("loading another alignment")); return False
        source = path.expanduser().resolve(strict=False); previous = self._state
        self._publish(replace(previous, phase=GuiPhase.LOADING_ALIGNMENT, progress_message="Validating alignment", active_failure=None))
        try: alignment = read_alignment(source)
        except ProjectError as exc:
            self._publish(replace(previous, active_failure=GuiFailure("Invalid alignment", str(exc), exc.code, "The previous valid alignment was kept.", source, source=FailureSource.ALIGNMENT_LOADING), progress_message="Choose another alignment file.")); return False
        except Exception:
            LOGGER.exception("unexpected alignment GUI load failure")
            self._publish(replace(previous, active_failure=GuiFailure("Unexpected alignment error", "The alignment could not be loaded.", "GUI_ALIGNMENT_INTERNAL", related_path=source, is_unexpected=True, source=FailureSource.ALIGNMENT_LOADING))); return False
        output = previous.output_directory or source.parent / "outputs"
        self._publish(GuiState(phase=GuiPhase.READY, alignment_path=source, output_directory=output, alignment=alignment, alignment_summary=summarize_alignment(alignment), progress_message="Alignment is ready. Review settings and generate subtitles.", warnings=alignment.warnings))
        return True

    def generate(self, settings: SubtitleSettings) -> bool:
        if self._task_lifecycle is not TaskLifecycle.IDLE or self._state.task_active:
            self.report_failure(self._busy_failure("starting another generation")); return False
        if self._state.alignment_path is None or self._state.output_directory is None:
            self.report_failure(GuiFailure("Cannot generate subtitles", "Select a valid alignment and output folder first.", "GUI_INPUT_NOT_READY", source=FailureSource.SETTINGS_VALIDATION)); return False
        request = GenerationRequest(self._state.alignment_path, self._state.output_directory, settings)
        if self._state.alignment is not None:
            LocalEnglishSyntaxAnalyzer().analyze(
                self._state.alignment.script.exact_text,
                self._state.alignment.aligned_words,
            )
        try:
            factory = self._service_factory; service = factory() if callable(factory) else factory
            thread = QThread(self); worker = self._worker_factory(request, service); worker.moveToThread(thread)
        except Exception:
            LOGGER.exception("worker setup failed"); self.report_failure(GuiFailure("Subtitle generation could not start", "The background task could not be created.", "GUI_WORKER_SETUP_FAILED", is_unexpected=True, source=FailureSource.INTERNAL)); return False
        self._wire_common(thread, worker)
        worker.progress.connect(self._on_progress)
        self._workflow = "subtitle"; self._phase_before_task = GuiPhase.SUCCESS if self._state.generated_result else GuiPhase.READY
        self._begin(thread, worker, GuiPhase.PROCESSING, "Starting subtitle generation")
        return True

    def start_full_processing(self, request: PipelineRunRequest) -> bool:
        if self._task_lifecycle is not TaskLifecycle.IDLE or self._state.task_active:
            self.report_failure(self._busy_failure("starting another processing run")); return False
        if self._full_service_factory is None:
            self.report_failure(GuiFailure("Processing service unavailable", "The full local pipeline is not configured.", "GUI_PIPELINE_UNAVAILABLE", source=FailureSource.INTERNAL)); return False
        script_words = tuple(
            token
            for token in tokenize_script(request.script_input.exact_text)
            if token.kind is ScriptTokenKind.WORD
        )
        LocalEnglishSyntaxAnalyzer().analyze(
            request.script_input.exact_text,
            script_words,
        )
        token = CancellationToken()
        try:
            thread = QThread(self); worker = self._full_worker_factory(request, self._full_service_factory, token); worker.moveToThread(thread)
        except Exception:
            LOGGER.exception("pipeline worker setup failed"); self.report_failure(GuiFailure("Processing could not start", "The background task could not be created.", "GUI_WORKER_SETUP_FAILED", is_unexpected=True, source=FailureSource.INTERNAL)); return False
        self._wire_common(thread, worker)
        worker.progress.connect(self._on_pipeline_progress); worker.cancelled.connect(self._on_pipeline_cancelled)
        self._workflow = "full"; self._phase_before_task = GuiPhase.INPUT_READY; self._cancellation_token = token
        self._begin(thread, worker, GuiPhase.PREFLIGHTING, "Starting local preflight")
        return True

    def _wire_common(self, thread: QThread, worker: QObject) -> None:
        thread.started.connect(worker.run); worker.started.connect(self._on_worker_started)
        worker.succeeded.connect(self._on_backend_success); worker.failed.connect(self._on_backend_failure)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished); thread.finished.connect(thread.deleteLater)

    def _begin(self, thread: QThread, worker: QObject, phase: GuiPhase, message: str) -> None:
        self._thread = thread; self._worker = worker; self._pending_result = None; self._pending_failure = None; self._pending_cancelled = False; self._pending_cleanup = None; self._task_lifecycle = TaskLifecycle.CREATED
        self._publish(replace(self._state, phase=phase, active_failure=None, task_active=True, pipeline_progress=None, completed_pipeline_stages=(), progress_message=message))
        thread.start()

    def request_cancellation(self) -> bool:
        token = self._cancellation_token
        if not self._state.task_active or token is None: return False
        accepted = token.request()
        if accepted: self._publish(replace(self._state, phase=GuiPhase.CANCELLING, progress_message="Cancel requested — stopping after the current safe step."))
        return accepted

    @Slot()
    def _on_worker_started(self) -> None: self._task_lifecycle = TaskLifecycle.RUNNING

    @Slot(str)
    def _on_progress(self, message: str) -> None:
        if self._state.task_active: self._publish(replace(self._state, progress_message=message))

    @Slot(object)
    def _on_pipeline_progress(self, item: object) -> None:
        if not isinstance(item, PipelineProgress) or not self._state.task_active: return
        cancelling = bool(self._cancellation_token and self._cancellation_token.requested)
        phase = GuiPhase.CANCELLING if cancelling else (GuiPhase.PREFLIGHTING if item.stage.value == "preflight" else GuiPhase.PROCESSING)
        completed = self._state.completed_pipeline_stages; previous = self._state.pipeline_progress
        if previous is not None and previous.stage.value not in completed: completed = (*completed, previous.stage.value)
        self._publish(replace(self._state, phase=phase, pipeline_progress=item, completed_pipeline_stages=completed, progress_message=f"Step {item.stage_index} of {item.total_stages}: {item.message}"))

    @Slot(object)
    def _on_backend_success(self, result: object) -> None:
        if isinstance(result, (GeneratedResult, PipelineRunResult)):
            self._pending_result = result; self._task_lifecycle = TaskLifecycle.BACKEND_SUCCEEDED
        else:
            self._pending_failure = GuiFailure("Unexpected worker result", "The task returned an unsupported result.", "GUI_WORKER_RESULT_INVALID", is_unexpected=True, source=FailureSource.INTERNAL); self._task_lifecycle = TaskLifecycle.BACKEND_FAILED
        self._enter_finishing()

    @Slot(object)
    def _on_backend_failure(self, failure: object) -> None:
        self._pending_failure = failure if isinstance(failure, GuiFailure) else GuiFailure("Unexpected worker error", "The task failed without structured details.", "GUI_WORKER_FAILURE_INVALID", is_unexpected=True, source=FailureSource.INTERNAL)
        self._task_lifecycle = TaskLifecycle.BACKEND_FAILED; self._enter_finishing()

    @Slot(object)
    def _on_pipeline_cancelled(self, cleanup: object = None) -> None:
        self._pending_cancelled = True
        self._pending_cleanup = cleanup if isinstance(cleanup, PipelineCleanupOutcome) else None
        self._enter_finishing()

    def _enter_finishing(self) -> None:
        self._task_lifecycle = TaskLifecycle.FINISHING
        self._publish(replace(self._state, phase=GuiPhase.FINISHING, progress_message="Finalizing and cleaning up the background task…", task_active=True))

    @Slot()
    def _thread_finished(self) -> None:
        # ``QThread.finished`` is emitted just before native thread-local cleanup.
        # Wait for that final cleanup before releasing the Python worker wrapper or
        # reading/publishing artifacts on the GUI thread.  This is a no-op for an
        # already stopped thread and prevents a Shiboken deletion race on macOS.
        thread = self._thread
        if thread is not None and QThread.currentThread() is not thread:
            thread.wait()
        result, failure, cancelled, cleanup = self._pending_result, self._pending_failure, self._pending_cancelled, self._pending_cleanup
        self._worker = None; self._thread = None; self._pending_result = None; self._pending_failure = None; self._pending_cancelled = False; self._pending_cleanup = None; self._cancellation_token = None; self._task_lifecycle = TaskLifecycle.IDLE
        if isinstance(result, PipelineRunResult):
            alignment = read_alignment(result.alignment_path)
            self._publish(replace(self._state, phase=GuiPhase.SUCCESS, alignment=alignment, alignment_path=result.alignment_path, alignment_summary=summarize_alignment(alignment), pipeline_result=result, generated_result=None, active_failure=None, warnings=result.warnings, progress_message="Voiceover package is ready.", task_active=False)); return
        if isinstance(result, GeneratedResult):
            document = result.document; warnings = tuple(document.warnings) + tuple(w for block in document.blocks for w in block.warnings)
            self._publish(replace(self._state, phase=GuiPhase.SUCCESS, generated_result=result, active_failure=None, progress_message="Subtitle files are ready.", warnings=tuple(sorted(set(warnings))), task_active=False)); return
        if cancelled:
            if cleanup is None:
                cleanup_text = " Cleanup status is unavailable."
            elif cleanup.attempted and cleanup.completed:
                cleanup_text = " Temporary workspace was removed."
            elif not cleanup.attempted and cleanup.completed:
                cleanup_text = " No processing workspace was created."
            else:
                cleanup_text = " Temporary workspace could not be fully removed. Manual cleanup may be required."
            self._publish(replace(self._state, phase=GuiPhase.CANCELLED, active_failure=None, progress_message="Processing cancelled. No final output was published." + cleanup_text, task_active=False)); return
        issue = failure or GuiFailure("Processing ended unexpectedly", "No result was produced.", "GUI_WORKER_NO_OUTCOME", is_unexpected=True, source=FailureSource.INTERNAL)
        self._publish(replace(self._state, phase=self._phase_before_task, active_failure=issue, progress_message="Processing failed. Correct the problem and retry.", task_active=False))

    def wait_for_worker(self, milliseconds: int = 10_000) -> bool:
        return True if self._thread is None else self._thread.wait(milliseconds)
