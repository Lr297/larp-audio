"""Qt Widgets view: rendering and user-event forwarding only."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.config import AlignmentSettings, AudioSettings, ModelSettings, PauseSettings, desktop_mvp_pause_settings
from larp_audio_mvp.core.errors import ConfigurationError, ProjectError
from larp_audio_mvp.core.logging import get_logger
from larp_audio_mvp.audio import ExecutableResolver, FfprobeAdapter, SubprocessRunner

from .controller import GuiController
from .desktop import DesktopService
from .dialogs import DialogService, QtDialogService
from .models import SubtitleBlockTableModel, WarningFilterProxyModel
from .workers import AudioPreflightWorker, PreviewPreparationWorker
from .preview import PreviewController, PreviewPreparationService, QtMediaBackend
from .preview.contracts import PlaybackState, PreviewSource, PreviewState
from .preview.widgets import PreviewPanel, format_preview_time
from .production_workspace import build_production_workspace
from .presets import PAUSE_PRESETS, PausePresetValues, PauseStylePreset, identify_pause_preset
from .path_display import ElidedPathLabel
from .state import (
    FailureSource,
    GuiFailure,
    GuiPhase,
    GuiState,
    AudioPreflightRequest,
    AudioPreflightResult,
    format_failure_details,
)
from larp_audio_mvp.pipeline.contracts import PipelineRunRequest, ScriptSourceKind
from larp_audio_mvp.pipeline.factory import create_full_processing_service
from larp_audio_mvp.pipeline.script_input import create_script_input, load_script_input, script_input_from_editor
from larp_audio_mvp.runtime import ApplicationPaths, BundledResourceResolver, default_application_paths, developer_mode_enabled
from larp_audio_mvp.runtime.migration import migrate_legacy_preferences
from larp_audio_mvp.runtime.migration import migrate_subtitle_word_limit
from larp_audio_mvp.speech_engine import EngineReadiness, SpeechEngineManager
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing
from larp_audio_mvp.version import RELEASE_VERSION
from .speech_setup import SpeechEngineSetupDialog
from .universal_export_dialog import UniversalExportDialog

PRODUCT_NAME = "LARP Audio"
LOGGER = get_logger("gui.main_window")


def _default_audio_probe() -> FfprobeAdapter:
    settings = AudioSettings()
    development = developer_mode_enabled()
    try:
        ffprobe = BundledResourceResolver.current(developer_mode=development).media_tool("ffprobe")
    except ConfigurationError:
        # Source-only compatibility. Installed builds never silently depend on PATH.
        if not development:
            raise
        ffprobe = ExecutableResolver().resolve("ffprobe")
    return FfprobeAdapter(
        runner=SubprocessRunner(), ffprobe_path=ffprobe, settings=settings
    )


def _fraction(value: Fraction) -> str:
    with localcontext() as context:
        context.prec = 16
        return format(Decimal(value.numerator) / Decimal(value.denominator), ".2f")


def _duration(samples: int, sample_rate: int) -> str:
    return f"{samples / sample_rate:.2f} s"


def _compact_audio_duration(total_samples: int | None, sample_rate: int) -> str:
    if total_samples is None or sample_rate <= 0:
        return "UNKNOWN"
    total_seconds = total_samples // sample_rate
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        controller: GuiController | None = None,
        dialogs: DialogService | None = None,
        desktop: DesktopService | None = None,
        settings: QSettings | None = None,
        audio_probe_factory: object | None = None,
        media_backend_factory: object | None = None,
        preview_service_factory: object | None = None,
        application_paths: ApplicationPaths | None = None,
        speech_engine_manager: SpeechEngineManager | None = None,
        developer_mode: bool | None = None,
    ) -> None:
        super().__init__()
        self.developer_mode = developer_mode_enabled() if developer_mode is None else developer_mode
        self.application_paths = application_paths or default_application_paths()
        self.application_paths.ensure()
        self.speech_engine_manager = speech_engine_manager or SpeechEngineManager(self.application_paths.data_directory)
        resources = BundledResourceResolver.current(developer_mode=self.developer_mode)
        if controller is None:
            def full_service_factory(request: PipelineRunRequest):
                return create_full_processing_service(
                    audio_settings=request.audio_settings,
                    pause_settings=request.pause_settings,
                    alignment_settings=request.alignment_settings,
                    bundled_tools_directory=resources.media_directory,
                    allow_system_tools=self.developer_mode,
                )
            controller = GuiController(full_service_factory=full_service_factory, parent=self)
        self.controller = controller
        self.dialogs = dialogs or QtDialogService()
        self.desktop = desktop or DesktopService()
        self.preferences = settings or QSettings()
        self._state = self.controller.state
        self._close_notice: QMessageBox | None = None
        self._speech_setup_dialog: SpeechEngineSetupDialog | None = None
        self._close_after_speech_setup = False
        self._export_dialog: UniversalExportDialog | None = None
        self._close_after_export = False
        self._updating_script_editor = False
        self._model_valid = False
        self._applying_pause_preset = False
        self.pause_style = PauseStylePreset.BALANCED
        self._audio_preflight_sequence = 0
        self._audio_preflight_threads: dict[str, tuple[QThread, AudioPreflightWorker]] = {}
        self._audio_preflight_thread: QThread | None = None
        self._audio_probe_factory = audio_probe_factory or _default_audio_probe
        self._media_backend_factory = media_backend_factory
        self._preview_service_factory = preview_service_factory or PreviewPreparationService
        self._preview_thread: QThread | None = None
        self._preview_worker: PreviewPreparationWorker | None = None
        self._preview_requested_run_id: str | None = None
        self._result_opened_run_id: str | None = None
        self._start_over_after_task = False
        self.preview_controller: PreviewController | None = None
        self._build_ui()
        self._script_autosave_timer = QTimer(self)
        self._script_autosave_timer.setSingleShot(True)
        self._script_autosave_timer.setInterval(500)
        self._script_autosave_timer.timeout.connect(self._persist_script)
        self._quit_shortcut = QShortcut(QKeySequence.Quit, self)
        self._quit_shortcut.activated.connect(self.request_application_quit)
        self._initialize_preview()
        self._restore_preferences()
        self.controller.state_changed.connect(self.render_state)
        self.render_state(self.controller.state)
        self.setAcceptDrops(True)

    def _build_ui(self) -> None:
        build_production_workspace(self)

    def _initialize_preview(self) -> None:
        try:
            factory = self._media_backend_factory
            backend = factory() if callable(factory) else (factory or QtMediaBackend(self))
            self.preview_controller = PreviewController(backend)
            self.preview_controller.state_changed.connect(self._render_preview_state)
        except ProjectError as exc:
            LOGGER.warning("preview backend unavailable code=%s", exc.code)
            self.preview_controller = None
            self.preview_panel.cue_viewport.set_text("Preview unavailable")
            self.preview_panel.cue_meta.setText(f"{exc.code}: {exc}")
        panel = self.preview_panel
        panel.play_button.clicked.connect(lambda: self.preview_controller and self.preview_controller.play_pause())
        panel.stop_button.clicked.connect(lambda: self.preview_controller and self.preview_controller.stop())
        panel.previous_button.clicked.connect(lambda: self.preview_controller and self.preview_controller.previous_cue())
        panel.next_button.clicked.connect(lambda: self.preview_controller and self.preview_controller.next_cue())
        panel.reload_button.clicked.connect(self.reload_preview)
        panel.seek_slider.sliderReleased.connect(self._preview_seek_released)
        panel.volume_slider.valueChanged.connect(lambda value: self.preview_controller and self.preview_controller.set_volume(value))
        panel.mute.toggled.connect(lambda value: self.preview_controller and self.preview_controller.set_muted(value))
        panel.follow.toggled.connect(lambda value: self.preview_controller and self.preview_controller.set_follow_playback(value))
        panel.auto_scroll.toggled.connect(lambda value: self.preview_controller and self.preview_controller.set_auto_scroll(value))
        self.subtitle_table.clicked.connect(self._preview_row_selected)
        self.subtitle_table.doubleClicked.connect(self._preview_row_activated)
        self.preview_block_list.currentRowChanged.connect(lambda row: self.preview_controller and self.preview_controller.select(row + 1 if row >= 0 else None))
        self.preview_block_list.itemDoubleClicked.connect(lambda item: self.preview_controller and self.preview_controller.seek_to_block(self.preview_block_list.row(item) + 1))
        self._render_preview_state(PreviewState())

    def _start_preview_preparation(self, result: object) -> None:
        from larp_audio_mvp.pipeline.contracts import PipelineRunResult
        if not isinstance(result, PipelineRunResult) or self.preview_controller is None:
            return
        if self._preview_thread is not None or self._preview_requested_run_id == result.run_id:
            return
        self._preview_requested_run_id = result.run_id
        self.preview_controller.reset()
        thread = QThread(self); worker = PreviewPreparationWorker(result, self._preview_service_factory)
        worker.moveToThread(thread); thread.started.connect(worker.run)
        worker.succeeded.connect(self._preview_prepared); worker.failed.connect(self._preview_preparation_failed)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._preview_preparation_finished); thread.finished.connect(thread.deleteLater)
        self._preview_thread = thread; self._preview_worker = worker; thread.start()

    def _preview_prepared(self, source: object) -> None:
        if isinstance(source, PreviewSource) and self.preview_controller is not None and source.run_id == self._preview_requested_run_id:
            self.preview_controller.load(source)
            self._populate_preview_diagnostics(source)
            self._populate_artifacts()

    def _preview_preparation_failed(self, failure: object) -> None:
        if isinstance(failure, GuiFailure):
            self.controller.report_failure(failure)

    def _preview_preparation_finished(self) -> None:
        thread = self._preview_thread
        if thread is not None and QThread.currentThread() is not thread: thread.wait()
        self._preview_thread = None; self._preview_worker = None
        current = self.controller.state.pipeline_result
        if current is not None and current.run_id != self._preview_requested_run_id:
            self._start_preview_preparation(current)

    def reload_preview(self) -> None:
        result = self.controller.state.pipeline_result
        if result is None or self._preview_thread is not None:
            return
        self._preview_requested_run_id = None
        self._start_preview_preparation(result)

    def _render_preview_state(self, state: object) -> None:
        if not isinstance(state, PreviewState): return
        panel = self.preview_panel; enabled = state.media_available and state.source_loaded
        for widget in (panel.play_button, panel.stop_button, panel.previous_button, panel.next_button, panel.seek_slider, panel.volume_slider, panel.mute): widget.setEnabled(enabled)
        panel.reload_button.setEnabled(self.controller.state.pipeline_result is not None and self._preview_thread is None)
        panel.play_button.setText("Pause" if state.playback_state is PlaybackState.PLAYING else "Play")
        panel.current_time.setText(format_preview_time(state.position_milliseconds)); panel.total_time.setText(format_preview_time(state.duration_milliseconds))
        panel.seek_slider.blockSignals(True); panel.seek_slider.setRange(0, max(0, state.duration_milliseconds)); panel.seek_slider.setValue(state.position_milliseconds); panel.seek_slider.blockSignals(False)
        source = state.source
        block = None if source is None or state.active_block_index is None else source.subtitle_document.blocks[state.active_block_index - 1]
        for row in range(self.preview_block_list.count()):
            item = self.preview_block_list.item(row)
            item.setBackground(QColor(217, 74, 93, 33) if row + 1 == state.active_block_index else QColor(0, 0, 0, 0))
        if block is None:
            panel.cue_viewport.set_text("")
            panel.cue_meta.setText("" if state.source_loaded else "Process audio to prepare preview")
            panel.warning_badge.setText("")
            self.table_model.set_active_block(None)
        else:
            panel.cue_viewport.set_text("\n".join(block.display_lines))
            interval = apply_gapless_display_timing(source.subtitle_document)[
                block.block_index - 1
            ]
            start = format_preview_time(
                interval.display_start_sample * 1000 // source.sample_rate
            )
            end = format_preview_time(
                interval.display_end_sample * 1000 // source.sample_rate
            )
            panel.cue_meta.setText(f"Cue {block.block_index} · {start} – {end} · {block.timing_provenance.value} · {float(block.characters_per_second):.2f} CPS · {block.word_count} words")
            markers = list(block.warnings)
            if block.contains_interpolated_words: markers.append("Interpolated timing")
            if block.contains_unresolved_words: markers.append("Unresolved words")
            panel.warning_badge.setText("Warning: " + "; ".join(markers) if markers else "")
            self.table_model.set_active_block(block.block_index)
            source_index = self.table_model.index(block.block_index - 1, 0); proxy_index = self.warning_proxy.mapFromSource(source_index)
            if proxy_index.isValid():
                if state.auto_scroll: self.subtitle_table.scrollTo(proxy_index)
            else: panel.warning_badge.setText(panel.warning_badge.text() + " · Active cue hidden by filter")
        if state.failure is not None:
            panel.cue_viewport.set_text("Preview error"); panel.cue_meta.setText(f"{state.failure.code}: {state.failure.message}")
            active = self.controller.state.active_failure
            if active is None or active.error_code != state.failure.code:
                self.controller.report_failure(GuiFailure(
                    "Preview unavailable", state.failure.message, state.failure.code,
                    "The completed pipeline result and artifacts remain available.",
                    source=FailureSource.PREVIEW,
                ))

    def _preview_seek_released(self) -> None:
        if self.preview_controller: self.preview_controller.seek(self.preview_panel.seek_slider.value())

    def _preview_space_shortcut(self) -> None:
        focus = QApplication.focusWidget()
        if focus is self.script_editor or (focus is not None and self.script_editor.isAncestorOf(focus)):
            return
        if self.preview_controller:
            self.preview_controller.play_pause()

    def _preview_row_selected(self, index: object) -> None:
        from PySide6.QtCore import QModelIndex
        if self.preview_controller and isinstance(index, QModelIndex):
            source = self.warning_proxy.mapToSource(index); self.preview_controller.select(source.row() + 1)

    def _preview_row_activated(self, index: object) -> None:
        from PySide6.QtCore import QModelIndex
        if self.preview_controller and isinstance(index, QModelIndex):
            source = self.warning_proxy.mapToSource(index); self.preview_controller.seek_to_block(source.row() + 1)

    def _populate_preview_diagnostics(self, source: PreviewSource) -> None:
        self.diagnostics_list.clear()
        document = source.subtitle_document
        self.diagnostics_summary.setText(
            f"Cleaned duration: {format_preview_time(source.cleaned_total_samples * 1000 // source.sample_rate)}   ·   "
            f"Subtitle blocks: {len(document.blocks)}   ·   "
            f"Warnings: {sum(bool(block.warnings) for block in document.blocks)}   ·   "
            f"Text coverage: {float(document.diagnostics.text_coverage) * 100:.1f}%"
        )
        for entry in source.diagnostics.entries:
            self.diagnostics_list.addItem(f"[{entry.severity.value.upper()}] {entry.section} · {entry.label}: {entry.value}")

    def _populate_artifacts(self) -> None:
        self.artifact_list.clear(); result = self.controller.state.pipeline_result
        if result is None: return
        files = (
            ("Cleaned audio", result.cleaned_audio_path),
            ("Subtitles", result.srt_path),
            ("Subtitle blocks", result.subtitle_blocks_path),
            ("Processing report", result.processing_report_path),
            ("Full package", result.package_zip_path),
            ("Technical · edit map", result.edit_map_path),
            ("Technical · recognition", result.recognition_path),
            ("Technical · alignment", result.alignment_path),
            ("Technical · manifest", result.manifest_path),
        )
        for display, path in files:
            self.artifact_list.addItem(f"{display}   ·   Validated   ·   {path.stat().st_size:,} bytes")

    def _restore_preferences(self) -> None:
        geometry = self.preferences.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        legacy_word_limit = self.preferences.value(
            "subtitle_max_words_per_block",
            self.preferences.value("max_words_per_block", 10),
        )
        migrated_word_limit, changed = migrate_subtitle_word_limit(
            legacy_word_limit
        )
        self.max_words.setValue(migrated_word_limit)
        if changed:
            self.preferences.setValue(
                "subtitle_max_words_per_block", migrated_word_limit
            )
        if self.developer_mode:
            last_output = self.preferences.value("last_output_directory", "")
            if isinstance(last_output, str) and last_output:
                self.controller.set_output_directory(Path(last_output))
            last_model = self.preferences.value("last_model_directory", "")
            if isinstance(last_model, str) and last_model:
                self._set_model_path(Path(last_model))
        else:
            engine = self.speech_engine_manager.status()
            last_output_value = self.preferences.value("last_output_directory", "")
            last_model_value = self.preferences.value("last_model_directory", "")
            decision = migrate_legacy_preferences(
                legacy_model=Path(last_model_value) if isinstance(last_model_value, str) and last_model_value else None,
                legacy_output=Path(last_output_value) if isinstance(last_output_value, str) and last_output_value else None,
                managed_model=engine.model_path if engine.readiness is EngineReadiness.READY else None,
                default_output=self.application_paths.results_directory,
                application_data=self.application_paths.data_directory,
            )
            self.controller.set_output_directory(decision.output_directory)
            if engine.readiness is EngineReadiness.READY and engine.model_path is not None:
                self.model_name.setCurrentText("small")
                self._set_model_path(engine.model_path)
            else:
                self._model_valid = False
                self.model_status.setText("Setup required" if engine.readiness is EngineReadiness.NOT_INSTALLED else "Repair required")
        widths = self.preferences.value("subtitle_table_column_widths", [])
        if isinstance(widths, list):
            for column, width in enumerate(widths[: self.table_model.columnCount()]):
                try:
                    numeric = int(width)
                except (TypeError, ValueError):
                    continue
                if numeric > 0:
                    self.subtitle_table.setColumnWidth(column, numeric)
        restored_script = self.preferences.value("last_exact_script", "")
        if isinstance(restored_script, str) and restored_script and not restored_script.isspace():
            try:
                value = create_script_input(
                    restored_script,
                    source_kind=ScriptSourceKind.TYPED,
                    was_edited_in_gui=True,
                )
            except ProjectError:
                value = None
            if value is not None:
                self._updating_script_editor = True
                self.script_editor.setPlainText(restored_script)
                self._updating_script_editor = False
                self.controller.set_script_input(value)
                self._update_script_counter(value)

    def choose_audio(self) -> None:
        try:
            selected = self.dialogs.choose_audio(self)
        except Exception:
            self._report_unexpected("Audio dialog failed", "GUI_DIALOG_FAILED", FailureSource.DIALOG_ACTION); return
        if selected is not None:
            path = selected.expanduser().resolve(strict=False)
            if not path.is_file():
                self.controller.report_failure(GuiFailure("Invalid audio", "Select a local audio file.", "PIPELINE_INPUT_INVALID", related_path=path, source=FailureSource.DIALOG_ACTION)); return
            self._start_audio_preflight(path)

    def _start_audio_preflight(self, path: Path) -> None:
        normalized = path.expanduser().resolve(strict=False)
        try:
            stat = normalized.stat()
            size, mtime = stat.st_size, stat.st_mtime_ns
        except OSError:
            size, mtime = None, None
        self._audio_preflight_sequence += 1
        request = AudioPreflightRequest(
            request_id=f"audio-{self._audio_preflight_sequence}-{uuid.uuid4().hex}",
            source_path=normalized,
            normalized_path_identity=os.path.normcase(os.path.normpath(str(normalized))),
            sequence_number=self._audio_preflight_sequence,
            source_size_bytes=size,
            source_mtime_ns=mtime,
        )
        if not self.controller.begin_audio_preflight(request):
            return
        thread = QThread(self)
        worker = AudioPreflightWorker(request, self._audio_probe_factory)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._audio_preflight_completed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda request_id=request.request_id: self._audio_preflight_finished(request_id)
        )
        thread.finished.connect(thread.deleteLater)
        self._audio_preflight_threads[request.request_id] = (thread, worker)
        self._audio_preflight_thread = thread
        thread.start()

    def _audio_preflight_completed(self, result: object) -> None:
        if isinstance(result, AudioPreflightResult):
            self.controller.apply_audio_preflight_result(result)

    def _audio_preflight_finished(self, request_id: str) -> None:
        pair = self._audio_preflight_threads.pop(request_id, None)
        thread = pair[0] if pair is not None else None
        if thread is not None and QThread.currentThread() is not thread:
            thread.wait()
        self._audio_preflight_thread = (
            next(iter(self._audio_preflight_threads.values()))[0]
            if self._audio_preflight_threads
            else None
        )
        self.render_state(self.controller.state)

    def choose_script(self) -> None:
        try:
            selected = self.dialogs.choose_script(self)
            if selected is None: return
            value = load_script_input(selected)
        except ProjectError as exc:
            self.controller.report_failure(GuiFailure("Invalid script", str(exc), exc.code, source=FailureSource.DIALOG_ACTION)); return
        except Exception:
            self._report_unexpected("Script dialog failed", "GUI_DIALOG_FAILED", FailureSource.DIALOG_ACTION); return
        self._updating_script_editor = True
        self.script_editor.setPlainText(value.exact_text)
        self._updating_script_editor = False
        self.controller.set_script_input(value)
        self._update_script_counter(value)
        self._persist_script()

    def clear_script(self) -> None:
        self._script_autosave_timer.stop()
        self._updating_script_editor = True; self.script_editor.clear(); self._updating_script_editor = False
        self.controller.set_script_input(None); self._update_script_counter(None)
        self.preferences.remove("last_exact_script")
        self.preferences.sync()

    def remove_audio(self) -> None:
        self.controller.set_source_audio(None)

    def start_over(self) -> None:
        self._persist_script()
        if self.controller.state.task_active:
            answer = QMessageBox.question(
                self,
                "Cancel processing?",
                "Cancel the current processing run and start over?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self._start_over_after_task = True
                self.controller.request_cancellation()
            return
        retained_script = self.controller.state.script_input
        if self.preview_controller is not None:
            self.preview_controller.reset()
        self._preview_requested_run_id = None
        self._result_opened_run_id = None
        self.controller.reset_project_inputs()
        if retained_script is not None:
            self.controller.set_script_input(retained_script)
        self._update_script_counter(retained_script)
        self.set_pause_preset(PauseStylePreset.BALANCED)

    def _pause_values(self) -> PausePresetValues:
        return PausePresetValues(
            Decimal(str(self.pause_threshold.value())),
            self.minimum_detected_silence.value(),
            self.minimum_pause_to_shorten.value(),
            self.retained_pause.value(),
            self.maximum_pause_removal.value(),
        )

    def set_pause_preset(self, preset: str | PauseStylePreset) -> None:
        choice = PauseStylePreset(preset)
        if choice is PauseStylePreset.CUSTOM:
            return
        values = PAUSE_PRESETS[choice]
        self._applying_pause_preset = True
        try:
            self.pause_threshold.setValue(float(values.silence_threshold_db))
            self.minimum_detected_silence.setValue(values.minimum_detected_silence_ms)
            self.minimum_pause_to_shorten.setValue(values.minimum_pause_to_shorten_ms)
            self.retained_pause.setValue(values.retained_pause_ms)
            self.maximum_pause_removal.setValue(values.maximum_removed_per_pause_ms)
        finally:
            self._applying_pause_preset = False
        self._show_pause_style(choice)

    def _pause_exact_value_changed(self, _value: object = None) -> None:
        if not self._applying_pause_preset:
            self._show_pause_style(identify_pause_preset(self._pause_values()))

    def _show_pause_style(self, preset: PauseStylePreset) -> None:
        self.pause_style = preset
        for key, button in self.pause_preset_buttons.items():
            button.setChecked(key == preset.value)
        self.custom_preset_label.setVisible(preset is PauseStylePreset.CUSTOM)

    def restore_all_defaults(self) -> None:
        self.restore_defaults()
        self.set_pause_preset(PauseStylePreset.BALANCED)
        defaults = ModelSettings()
        self.model_name.setCurrentText(defaults.whisper_model)
        self.device.setCurrentText(defaults.device)
        self.compute_type.setCurrentText(defaults.compute_type)
        self.recognition_language.clear()
        self.recognition_beam_size.setValue(defaults.beam_size)

    def _script_edited(self) -> None:
        if self._updating_script_editor: return
        text = self.script_editor.toPlainText()
        self._script_autosave_timer.start()
        if not text or text.isspace():
            self.controller.set_script_input(None); self._update_script_counter(None); return
        try:
            value = script_input_from_editor(text, self.controller.state.script_input, user_edited=True)
        except ProjectError as exc:
            self.controller.report_failure(GuiFailure("Invalid script", str(exc), exc.code, source=FailureSource.SETTINGS_VALIDATION)); return
        self.controller.set_script_input(value); self._update_script_counter(value)

    def _persist_script(self) -> None:
        """Persist editor text locally; never log or copy it into diagnostics."""

        text = self.script_editor.toPlainText()
        if text:
            self.preferences.setValue("last_exact_script", text)
        else:
            self.preferences.remove("last_exact_script")
        self.preferences.sync()

    def _update_script_counter(self, value) -> None:
        self.script_counter.setText("0 characters · 0 words" if value is None else f"{value.character_count} characters · {value.script_word_count} words")

    def choose_model(self) -> None:
        if not self.developer_mode:
            self.prepare_speech_engine()
            return
        try:
            selected = self.dialogs.choose_model_directory(self, self.controller.state.local_model_path)
        except Exception:
            self._report_unexpected("Model dialog failed", "GUI_DIALOG_FAILED", FailureSource.DIALOG_ACTION); return
        if selected is not None: self._set_model_path(selected)

    def prepare_speech_engine(self, *, repair: bool = False) -> None:
        if self._speech_setup_dialog is not None:
            self._speech_setup_dialog.raise_()
            self._speech_setup_dialog.activateWindow()
            return
        dialog = SpeechEngineSetupDialog(self.speech_engine_manager, self, repair=repair)
        self._speech_setup_dialog = dialog
        dialog.engine_ready.connect(lambda value: self._set_model_path(Path(value)))
        dialog.lifecycle_finished.connect(self._speech_setup_lifecycle_finished)
        try:
            dialog.exec()
        finally:
            if self._speech_setup_dialog is dialog and not dialog.worker_active:
                self._speech_setup_dialog = None
        if self._close_after_speech_setup and self._speech_setup_dialog is None:
            QTimer.singleShot(0, self.close)

    def _speech_setup_lifecycle_finished(self, _outcome: str) -> None:
        dialog = self._speech_setup_dialog
        if dialog is not None and not dialog.worker_active:
            self._speech_setup_dialog = None
        if self._close_after_speech_setup:
            QTimer.singleShot(0, self.close)

    def request_application_quit(self) -> None:
        """Coordinate Cmd+Q with any active speech-engine setup worker."""
        self._close_after_speech_setup = True
        setup = self._speech_setup_dialog
        if setup is not None and setup.worker_active:
            setup.request_safe_close(close_dialog=True)
            return
        export = self._export_dialog
        if export is not None and export.worker_active:
            self._close_after_export = True
            export.request_safe_close()
            return
        self.close()

    def open_universal_export(self) -> None:
        result = self.controller.state.pipeline_result
        if result is None or not result.completed_successfully:
            return
        if self._export_dialog is not None:
            self._export_dialog.raise_()
            self._export_dialog.activateWindow()
            return
        source = self.controller.state.source_audio_path
        default_name = source.stem if source is not None else "LARP Audio"
        dialog = UniversalExportDialog(
            result,
            default_name,
            self.preferences,
            self.dialogs,
            self.desktop,
            self,
        )
        self._export_dialog = dialog
        dialog.lifecycle_finished.connect(self._export_lifecycle_finished)
        dialog.finished.connect(lambda _value: self._export_dialog_finished(dialog))
        dialog.show()

    def _export_lifecycle_finished(self, _outcome: str) -> None:
        if self._close_after_export:
            QTimer.singleShot(0, self.close)

    def _export_dialog_finished(self, dialog: UniversalExportDialog) -> None:
        if self._export_dialog is dialog and not dialog.worker_active:
            self._export_dialog = None

    def _set_model_path(self, selected: Path) -> None:
        path = selected.expanduser().resolve(strict=False)
        required = ("config.json", "model.bin", "tokenizer.json")
        missing = tuple(name for name in required if not (path / name).is_file()) if path.is_dir() else required
        self._model_valid = not missing
        self.model_status.setText(
            f"Ready · {self.model_name.currentText()} · {self.device.currentText()}"
            if self._model_valid else "Incomplete · missing " + ", ".join(missing)
        )
        self.controller.set_local_model(path)

    def start_full_processing(self) -> None:
        state = self.controller.state
        if state.script_input is None:
            self.controller.report_failure(GuiFailure("Original script required", "Paste, type, or load the exact original script.", "SCRIPT_EMPTY", source=FailureSource.SETTINGS_VALIDATION)); self.script_editor.setFocus(); return
        if not self._model_valid or state.local_model_path is None:
            if not self.developer_mode:
                self.prepare_speech_engine(repair=self.speech_engine_manager.status().readiness is EngineReadiness.DAMAGED)
                return
            self.controller.report_failure(GuiFailure("Local model is not ready", "Select a complete local Faster-Whisper model folder.", "LOCAL_WHISPER_MODEL_INVALID", related_path=state.local_model_path, source=FailureSource.SETTINGS_VALIDATION)); return
        if state.source_audio_path is None or state.output_directory is None:
            self.controller.report_failure(GuiFailure("Inputs are incomplete", "Select audio and an output folder.", "PIPELINE_INPUT_INVALID", source=FailureSource.SETTINGS_VALIDATION)); return
        try:
            subtitle_settings = self.subtitle_settings()
            pause_settings = PauseSettings(
                silence_threshold_db=Decimal(str(self.pause_threshold.value())),
                minimum_pause_duration_ms=self.minimum_detected_silence.value(),
                shortening_policy_version="desktop-mvp-v1",
                minimum_pause_to_shorten_ms=self.minimum_pause_to_shorten.value(),
                target_remaining_pause_ms=self.retained_pause.value(),
                maximum_removed_per_pause_ms=self.maximum_pause_removal.value(),
            )
            language = self.recognition_language.text().strip() or None
            model_settings = ModelSettings(model_path=state.local_model_path.resolve(), whisper_model=self.model_name.currentText(), device=self.device.currentText(), compute_type=self.compute_type.currentText(), language=language, beam_size=self.recognition_beam_size.value())
            request = PipelineRunRequest(state.source_audio_path, state.script_input, state.local_model_path, state.output_directory, AudioSettings(), pause_settings, model_settings, AlignmentSettings(), subtitle_settings, RELEASE_VERSION)
        except ConfigurationError as exc:
            self.controller.report_failure(GuiFailure("Invalid processing settings", str(exc), exc.code, source=FailureSource.SETTINGS_VALIDATION)); return
        self.controller.start_full_processing(request)

    def choose_alignment(self) -> None:
        try:
            selected = self.dialogs.choose_alignment(self)
        except Exception:
            self._report_unexpected("Alignment dialog failed", "GUI_DIALOG_FAILED", FailureSource.DIALOG_ACTION)
            return
        if selected is not None:
            self.controller.load_alignment(selected)

    def choose_output_directory(self) -> None:
        try:
            selected = self.dialogs.choose_output_directory(
                self, self.controller.state.output_directory
            )
        except Exception:
            self._report_unexpected("Output folder dialog failed", "GUI_DIALOG_FAILED", FailureSource.DIALOG_ACTION)
            return
        if selected is not None:
            candidate = selected.resolve(strict=False)
            data = self.application_paths.data_directory.resolve(strict=False)
            if candidate == data or data in candidate.parents or candidate in data.parents:
                self.controller.report_failure(GuiFailure("Choose a different results folder", "Application data and exported results must be stored separately.", "PIPELINE_MODEL_OUTPUT_OVERLAP", related_path=candidate, source=FailureSource.SETTINGS_VALIDATION)); return
            candidate.mkdir(parents=True, exist_ok=True)
            self.controller.set_output_directory(candidate)

    def check_speech_engine(self) -> None:
        status = self.speech_engine_manager.status()
        copy = {EngineReadiness.READY: "Ready and verified", EngineReadiness.NOT_INSTALLED: "Not installed", EngineReadiness.DAMAGED: "Repair required"}[status.readiness]
        self.engine_maintenance_status.setText(copy)
        self._model_valid = status.readiness is EngineReadiness.READY

    def remove_speech_engine(self) -> None:
        answer = QMessageBox.question(self, "Remove speech engine?", "This frees downloaded storage. It can be prepared again later.", QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.speech_engine_manager.remove()
        self._model_valid = False
        self.controller.set_local_model(None)
        self.model_status.setText("Setup required")
        self.engine_maintenance_status.setText("Not installed")
        self.render_state(self.controller.state)

    def subtitle_settings(self) -> SubtitleSettings:
        defaults = SubtitleSettings()
        return SubtitleSettings(
            max_lines=self.max_lines.value(),
            max_characters_per_line=self.max_chars.value(),
            max_words_per_block=defaults.max_words_per_block,
            min_duration_ms=self.min_duration.value(),
            max_duration_ms=self.max_duration.value(),
            max_characters_per_second=Decimal(str(self.max_cps.value())),
            preferred_gap_break_ms=defaults.preferred_gap_break_ms,
            strong_gap_break_ms=defaults.strong_gap_break_ms,
            preferred_min_words_per_block=defaults.preferred_min_words_per_block,
            preferred_min_visible_chars=defaults.preferred_min_visible_chars,
            new_block_penalty=defaults.new_block_penalty,
            single_word_block_penalty=defaults.single_word_block_penalty,
            short_block_penalty=defaults.short_block_penalty,
            max_unresolved_words_per_block=defaults.max_unresolved_words_per_block,
            minimum_timing_coverage_for_export=defaults.minimum_timing_coverage_for_export,
            allow_unresolved_attachment=defaults.allow_unresolved_attachment,
            max_segmentation_cells=defaults.max_segmentation_cells,
        )

    def start_generation(self) -> None:
        if self.min_duration.value() > self.max_duration.value():
            self.min_duration.setFocus()
            self.min_duration.setProperty("invalid", True)
            self.min_duration.style().unpolish(self.min_duration)
            self.min_duration.style().polish(self.min_duration)
            self.controller.report_failure(
                GuiFailure(
                    title="Invalid subtitle settings",
                    message="Minimum duration must not exceed maximum duration.",
                    error_code="CONFIGURATION_ERROR",
                    details=(
                        f"Parameter: minimum duration; entered: {self.min_duration.value()} ms; "
                        f"allowed: 100–{self.max_duration.value()} ms"
                    ),
                    source=FailureSource.SETTINGS_VALIDATION,
                )
            )
            return
        try:
            settings = self.subtitle_settings()
        except ConfigurationError as exc:
            self.controller.report_failure(
                GuiFailure(
                    title="Invalid subtitle settings",
                    message="Review the highlighted subtitle parameters.",
                    error_code=exc.code,
                    details=str(exc),
                    source=FailureSource.SETTINGS_VALIDATION,
                )
            )
            return
        self.min_duration.setProperty("invalid", False)
        self.controller.generate(settings)

    def restore_defaults(self) -> None:
        defaults = SubtitleSettings()
        self.max_chars.setValue(defaults.max_characters_per_line)
        self.max_lines.setValue(defaults.max_lines)
        self.max_words.setValue(defaults.max_words_per_block)
        self.min_duration.setValue(defaults.min_duration_ms)
        self.max_duration.setValue(defaults.max_duration_ms)
        self.max_cps.setValue(float(defaults.max_characters_per_second))

    def _set_advanced_visible(self, visible: bool) -> None:
        layout = self.advanced_group.layout()
        for widget in self._advanced_widgets:
            widget.setVisible(visible)
            if isinstance(layout, QFormLayout):
                label = layout.labelForField(widget)
                if label is not None:
                    label.setVisible(visible)

    def render_state(self, state: GuiState) -> None:
        self._state = state
        task_active = state.task_active
        if self._start_over_after_task and not task_active:
            self._start_over_after_task = False
            self.start_over()
            return
        if task_active and self.preview_controller is not None and self.preview_controller.state.source_loaded:
            self.preview_controller.reset()
            self._preview_requested_run_id = None
        ready = state.alignment is not None and not task_active
        success = state.phase is GuiPhase.SUCCESS and (state.generated_result is not None or state.pipeline_result is not None)
        full_ready = all((state.source_audio_path, state.script_input, state.local_model_path, state.output_directory)) and self._model_valid and state.audio_preflight_ready is True and not task_active
        stage_copy = {
            "preflight": "Preparing audio", "preparing_workspace": "Preparing audio",
            "analyzing_audio": "Preparing audio", "canonicalizing_audio": "Preparing audio",
            "detecting_pauses": "Removing pauses", "shortening_pauses": "Removing pauses",
            "rendering_cleaned_audio": "Removing pauses", "recognizing_speech": "Recognizing speech",
            "aligning_script": "Aligning script", "generating_subtitles": "Creating subtitle blocks",
            "validating_artifacts": "Validating result", "writing_reports": "Saving files",
            "creating_package": "Saving files", "publishing_results": "Saving files",
        }
        pipeline_progress = state.pipeline_progress
        stage = pipeline_progress.stage.value if pipeline_progress is not None else None
        user_status = stage_copy.get(stage, state.progress_message)
        if pipeline_progress is not None and pipeline_progress.total_stages > 0:
            self.status_message.setText(
                f"{user_status} · step {pipeline_progress.stage_index} "
                f"of {pipeline_progress.total_stages}"
            )
            self.progress.setRange(0, pipeline_progress.total_stages)
            self.progress.setValue(
                max(
                    pipeline_progress.completed_stage_count,
                    pipeline_progress.stage_index - 1,
                )
            )
        else:
            self.status_message.setText(user_status)
            self.progress.setRange(0, 0)
        event_copy = f"●  {user_status.upper()}"
        if task_active and (
            not self.processing_events.count()
            or self.processing_events.item(self.processing_events.count() - 1).text()
            != event_copy
        ):
            self.processing_events.addItem(event_copy)
            while self.processing_events.count() > 5: self.processing_events.takeItem(0)
            self.processing_events.setCurrentRow(self.processing_events.count() - 1)
        elif not task_active:
            self.processing_events.clear()
        self.processing_card.setVisible(task_active)
        self.audio_value.set_path_name(state.source_audio_path)
        if state.audio_preflight_metadata is not None:
            audio = state.audio_preflight_metadata
            duration = _compact_audio_duration(audio.total_samples, audio.sample_rate)
            channel_copy = "MONO" if audio.channels == 1 else f"{audio.channels} CH"
            self.audio_preflight_status.setText(
                f"{duration} · {(audio.format_name or 'AUDIO').upper()} · "
                f"{audio.sample_rate // 1_000:g} kHz · {channel_copy}"
            )
            size = "unknown" if audio.file_size_bytes is None else f"{audio.file_size_bytes:,} bytes"
            self.audio_preflight_status.setToolTip(
                f"Codec: {audio.codec_name or 'unknown'} · Sample rate: "
                f"{audio.sample_rate} Hz · Channels: {audio.channels} · Size: {size}"
            )
        elif state.audio_preflight_request is not None and state.audio_preflight_ready is False:
            self.audio_preflight_status.setText("Inspecting audio…")
        elif state.audio_preflight_ready is False:
            self.audio_preflight_status.setText("Audio could not be inspected")
        else:
            self.audio_preflight_status.setText("Your audio stays on this device")
        self.browse_audio_button.setText("Replace" if state.source_audio_path is not None else "Upload audio")
        self.remove_audio_button.setVisible(state.source_audio_path is not None)
        if self.developer_mode:
            self.model_value.set_path_name(state.local_model_path)
            self.full_output_value.set_path_name(state.output_directory)
        else:
            self.model_value.setText("Ready · multilingual" if self._model_valid else "Setup required · one-time download")
            self.model_value.setToolTip("")
            automatic = state.output_directory == self.application_paths.results_directory
            self.full_output_value.setText("Documents / LARP Audio Results" if automatic else "Custom results folder")
            self.full_output_value.setToolTip("")
        self.advanced_output_value.set_path_name(state.output_directory)
        for widget in (self.browse_audio_button, self.remove_audio_button, self.load_script_button, self.clear_script_button, self.browse_model_button, self.browse_full_output_button, self.script_editor, *self.pause_preset_buttons.values()):
            widget.setEnabled(not task_active)
        if not self.developer_mode:
            self.browse_model_button.setEnabled(not task_active and not self._model_valid)
            self.browse_model_button.setText("PREPARE ENGINE" if not self._model_valid else "SPEECH ENGINE")
            self.browse_full_output_button.setEnabled(False)
        self.process_button.setEnabled(bool(full_ready))
        self.process_button.setText("Processing…" if task_active else "Process")
        if task_active:
            self.readiness_label.setText("●  PROCESSING")
            readiness_name = "readinessReady"
        elif full_ready:
            self.readiness_label.setText("●  READY")
            readiness_name = "readinessReady"
        else:
            self.readiness_label.setText("NOT READY")
            readiness_name = "readinessBlocked"
        if self.readiness_label.objectName() != readiness_name:
            self.readiness_label.setObjectName(readiness_name)
            self.readiness_label.style().unpolish(self.readiness_label)
            self.readiness_label.style().polish(self.readiness_label)
        self.start_over_button.setEnabled(True)
        self.advanced_settings_button.setEnabled(not task_active)
        self.cancel_button.setVisible(task_active and self._workflow_is_full())
        self.cancel_button.setEnabled(state.phase not in (GuiPhase.CANCELLING, GuiPhase.FINISHING))
        self.cancel_button.setText("Cancelling…" if state.phase is GuiPhase.CANCELLING else "Cancel")
        self.browse_alignment_button.setEnabled(not task_active)
        self.browse_output_button.setEnabled(not task_active)
        for widget in (self.check_engine_button, self.repair_engine_button, self.remove_engine_button):
            widget.setEnabled(not task_active)
        self.generate_button.setEnabled(ready and state.output_directory is not None)
        self.advanced_group.setEnabled(not task_active)
        self.pipeline_settings_group.setEnabled(not task_active)
        self.empty_hint.setVisible(not success and not task_active)
        self.error_frame.setVisible(state.active_failure is not None)
        self.copy_error_button.setEnabled(state.active_failure is not None)
        self.dismiss_error_button.setEnabled(state.active_failure is not None)
        if state.active_failure is not None:
            self.error_label.setText(
                f"Error [{state.active_failure.error_code}] — {state.active_failure.message}"
            )
        else:
            self.error_label.clear()
        self.alignment_value.set_path(state.alignment_path)
        self.output_value.set_path(state.output_directory)
        self.summary_list.clear()
        self.script_preview.clear()
        if state.alignment_summary is not None and state.alignment is not None:
            summary = state.alignment_summary
            fields = (
                ("Script words", summary.script_word_count),
                ("ASR words", summary.asr_word_count),
                ("Matched words", summary.matched_word_count),
                ("Interpolated words", summary.interpolated_word_count),
                ("Unresolved words", summary.unresolved_word_count),
                ("Text alignment coverage", _fraction(summary.text_alignment_coverage)),
                ("Timing coverage", _fraction(summary.timing_coverage)),
                ("Sample rate", f"{summary.sample_rate} Hz"),
                ("Cleaned duration", _duration(summary.cleaned_duration_samples, summary.sample_rate)),
                ("Provenance", "Complete" if summary.provenance_complete else "Incomplete"),
                ("Schema", summary.schema_version),
                ("Warnings", summary.warnings_count),
            )
            self.summary_list.addItems([f"{name}: {value}" for name, value in fields])
            self.script_preview.setPlainText(state.alignment.script.exact_text)
        self.success_banner.setVisible(success)
        for widget in self.export_row_widgets:
            widget.setVisible(success and state.pipeline_result is not None)
        self.export_button.setEnabled(
            success and state.pipeline_result is not None and not task_active
        )
        self.result_tabs.setVisible(success)
        result_buttons = (
            self.open_folder_button, self.open_audio_button, self.open_zip_button, self.open_srt_button, self.open_json_button,
            self.copy_srt_button, self.copy_json_button, self.generate_again_button,
        )
        for button in result_buttons:
            button.setVisible(success)
            button.setEnabled(success and not task_active)
        if success:
            document = state.pipeline_result.subtitle_document if state.pipeline_result is not None else state.generated_result.document
            diagnostics = document.diagnostics
            self.table_model.set_document(document)
            self.preview_block_list.clear()
            self.preview_block_list.addItems([f"{block.block_index:02d}   {' / '.join(block.display_lines)}" for block in document.blocks])
            self.diagnostics_list.clear()
            self.diagnostics_list.addItems(
                [
                    f"Success — total blocks: {diagnostics.total_blocks}",
                    f"Single-word blocks: {diagnostics.single_word_blocks}",
                    f"Short blocks: {diagnostics.short_blocks}",
                    f"Maximum CPS: {_fraction(diagnostics.maximum_characters_per_second)}",
                    f"Blocks over CPS limit: {diagnostics.blocks_over_cps_limit}",
                    f"Interpolated blocks: {diagnostics.blocks_with_interpolated_words}",
                    f"Unresolved blocks: {diagnostics.blocks_with_unresolved_words}",
                    f"Internal subtitle gaps: {diagnostics.internal_gap_count}",
                    f"SRT gaps: {diagnostics.srt_gap_count}",
                    f"Subtitle overlaps: {diagnostics.overlap_count}",
                    f"Detected list items: {diagnostics.list_item_count}",
                    f"Merged list violations: {diagnostics.list_item_merge_violation_count}",
                    f"Protected unit violations: {diagnostics.protected_unit_violation_count}",
                    f"Orphan fragments: {diagnostics.orphan_fragment_count}",
                    f"Incomplete endings: {diagnostics.incomplete_ending_count}",
                    f"Trailing comma violations: {diagnostics.trailing_comma_violation_count}",
                    f"Two-line cues: {diagnostics.two_line_cue_count}",
                    f"Maximum cue/line characters: {diagnostics.maximum_plain_characters}/{diagnostics.maximum_render_line_characters}",
                    *[f"Warning — {warning}" for warning in state.warnings],
                ]
            )
            if state.pipeline_result is not None:
                summary = state.pipeline_result.summary
                self.diagnostics_list.addItems([
                    f"Removed samples: {summary.removed_samples}",
                    f"Package size: {summary.package_size_bytes} bytes",
                    *[f"Artifact — {path.name}" for path in (
                        state.pipeline_result.cleaned_audio_path,
                        state.pipeline_result.srt_path,
                        state.pipeline_result.subtitle_blocks_path,
                        state.pipeline_result.edit_map_path,
                        state.pipeline_result.recognition_path,
                        state.pipeline_result.alignment_path,
                        state.pipeline_result.processing_report_path,
                        state.pipeline_result.manifest_path,
                        state.pipeline_result.package_zip_path,
                    )],
                ])
            self.show_warnings_only.setEnabled(True)
            if state.pipeline_result is not None and self._result_opened_run_id != state.pipeline_result.run_id:
                self._result_opened_run_id = state.pipeline_result.run_id
                self.result_tabs.setCurrentIndex(0)
        elif not task_active:
            self.table_model.set_document((), 1)
            self.diagnostics_list.clear()
            self.show_warnings_only.blockSignals(True)
            self.show_warnings_only.setChecked(False)
            self.show_warnings_only.blockSignals(False)
            self.warning_proxy.set_warnings_only(False)
            self.show_warnings_only.setEnabled(False)
            self.preview_block_list.clear()
        self._update_filter_count()
        self.warning_status.setText(f"{len(state.warnings)} warnings")
        if success and state.pipeline_result is not None:
            self._start_preview_preparation(state.pipeline_result)

    def _workflow_is_full(self) -> bool:
        return self.controller.state.source_audio_path is not None

    def _set_warning_filter(self, enabled: bool) -> None:
        self.warning_proxy.set_warnings_only(enabled)
        self._update_filter_count()

    def _update_filter_count(self) -> None:
        self.filter_count_label.setText(
            f"Showing {self.warning_proxy.rowCount()} of {self.table_model.rowCount()}"
        )

    def _result_paths(self) -> tuple[Path, Path] | None:
        if self._state.pipeline_result is not None:
            return self._state.pipeline_result.subtitle_blocks_path, self._state.pipeline_result.srt_path
        result = self._state.generated_result
        if result is None:
            return None
        return result.summary.subtitle_blocks_path, result.summary.srt_path

    def _desktop_action(self, path: Path) -> None:
        try:
            self.desktop.open_path(path)
        except ProjectError as exc:
            self.controller.report_failure(
                GuiFailure(
                    title="Desktop action failed",
                    message=str(exc),
                    error_code=exc.code,
                    related_path=path,
                    source=FailureSource.DESKTOP_ACTION,
                )
            )
        except Exception:
            self._report_unexpected("Desktop action failed", "GUI_DESKTOP_INTERNAL", FailureSource.DESKTOP_ACTION, path)

    def open_output_folder(self) -> None:
        target = self._state.pipeline_result.final_output_directory if self._state.pipeline_result else self._state.output_directory
        if target: self._desktop_action(target)

    def open_cleaned_audio(self) -> None:
        if self._state.pipeline_result: self._desktop_action(self._state.pipeline_result.cleaned_audio_path)

    def open_zip(self) -> None:
        if self._state.pipeline_result: self._desktop_action(self._state.pipeline_result.package_zip_path)

    def start_again(self) -> None:
        if self._state.pipeline_result is not None: self.start_full_processing()
        else: self.start_generation()

    def open_srt(self) -> None:
        paths = self._result_paths()
        if paths:
            self._desktop_action(paths[1])

    def open_json(self) -> None:
        paths = self._result_paths()
        if paths:
            self._desktop_action(paths[0])

    def copy_srt_path(self) -> None:
        paths = self._result_paths()
        if paths:
            self._copy_path(paths[1])

    def copy_json_path(self) -> None:
        paths = self._result_paths()
        if paths:
            self._copy_path(paths[0])

    def _copy_path(self, path: Path) -> None:
        try:
            self.desktop.copy_path(path, QApplication.clipboard())
        except ProjectError as exc:
            self.controller.report_failure(
                GuiFailure(
                    title="Copy path failed",
                    message=str(exc),
                    error_code=exc.code,
                    related_path=path,
                    source=FailureSource.DESKTOP_ACTION,
                )
            )
        except Exception:
            self._report_unexpected("Copy path failed", "GUI_COPY_PATH_INTERNAL", FailureSource.DESKTOP_ACTION, path)

    def copy_selected_text(self) -> None:
        proxy_index = self.subtitle_table.currentIndex()
        source_index = (
            self.warning_proxy.mapToSource(proxy_index)
            if proxy_index.model() is self.warning_proxy
            else proxy_index
        )
        block = self.table_model.block_at(source_index.row())
        if block is not None:
            QApplication.clipboard().setText("\n".join(block.display_lines))

    def copy_error_details(self) -> None:
        failure = self._state.active_failure
        if failure is not None:
            QApplication.clipboard().setText(format_failure_details(failure))
            self.controller.set_progress_message("Error details copied.")

    def _report_unexpected(
        self,
        title: str,
        code: str,
        source: FailureSource,
        path: Path | None = None,
    ) -> None:
        LOGGER.exception("unexpected local GUI action failure code=%s", code)
        self.controller.report_failure(
            GuiFailure(
                title=title,
                message="The action could not be completed. Try again or check the logs.",
                error_code=code,
                related_path=path,
                is_unexpected=True,
                source=source,
            )
        )

    def show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowIcon(QApplication.windowIcon())
        dialog.setWindowTitle(f"About {PRODUCT_NAME}")
        layout = QVBoxLayout(dialog)
        heading = QLabel(f"{PRODUCT_NAME} {RELEASE_VERSION}")
        heading.setObjectName("title")
        body = QLabel(
            "A private desktop tool for turning voiceover audio and an original "
            "script into cleaned audio and timed subtitles.\n\n"
            "Processing stays on this device. The original script remains the "
            "source of displayed text, and preview uses the cleaned audio timeline.\n\n"
            "Speech timing and media processing run locally. Runtime license notices "
            "are included with the application."
        )
        body.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addWidget(buttons)
        dialog.exec()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self._set_audio_card_state("dragActive", True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: object) -> None:  # noqa: N802
        self._set_audio_card_state("dragActive", False)
        super().dragLeaveEvent(event)

    def _set_audio_card_state(self, name: str, value: bool) -> None:
        self.audio_card.setProperty(name, value)
        self.audio_card.style().unpolish(self.audio_card)
        self.audio_card.style().polish(self.audio_card)
        self.audio_card.update()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_audio_card_state("dragActive", False)
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            self.controller.report_failure(
                GuiFailure(
                    title="Invalid drop",
                    message="Drop exactly one local audio or media file.",
                    error_code="GUI_DROP_INVALID",
                    details=f"Dropped item count: {len(urls)}; local file required.",
                    source=FailureSource.DRAG_AND_DROP,
                )
            )
            event.ignore()
            return
        path = Path(urls[0].toLocalFile())
        if not path.is_file():
            self.controller.report_failure(
                GuiFailure(
                    title="Invalid drop",
                    message="The dropped item is not a local file.",
                    error_code="GUI_DROP_INVALID",
                    related_path=path,
                    source=FailureSource.DRAG_AND_DROP,
                )
            )
            event.ignore()
            return
        self._start_audio_preflight(path.resolve(strict=False))
        self._set_audio_card_state("accepted", True)
        QTimer.singleShot(160, lambda: self._set_audio_card_state("accepted", False))
        event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        setup = self._speech_setup_dialog
        if setup is not None and setup.worker_active:
            self._close_after_speech_setup = True
            setup.request_safe_close(close_dialog=True)
            event.ignore()
            return
        export = self._export_dialog
        if export is not None and export.worker_active:
            self._close_after_export = True
            export.request_safe_close()
            event.ignore()
            return
        if self.controller.state.processing or self._audio_preflight_threads or self._preview_thread is not None:
            event.ignore()
            if self._close_notice is None or not self._close_notice.isVisible():
                notice = QMessageBox(QMessageBox.Information, "Operation in progress", "Subtitle generation is still running. Wait for it to finish before closing.", QMessageBox.Ok, self)
                notice.setModal(False)
                notice.finished.connect(lambda _result: setattr(self, "_close_notice", None))
                self._close_notice = notice
                notice.show()
            return
        self.preferences.setValue("window_geometry", self.saveGeometry())
        self._script_autosave_timer.stop()
        self._persist_script()
        self.preferences.setValue("advanced_expanded", self.advanced_group.isChecked())
        self.preferences.setValue(
            "subtitle_table_column_widths",
            [
                self.subtitle_table.columnWidth(column)
                for column in range(self.table_model.columnCount())
            ],
        )
        if self.controller.state.output_directory is not None:
            self.preferences.setValue(
                "last_output_directory", str(self.controller.state.output_directory)
            )
        if self.developer_mode and self.controller.state.local_model_path is not None:
            self.preferences.setValue("last_model_directory", str(self.controller.state.local_model_path))
        self.preferences.sync()
        if self.preview_controller is not None:
            self.preview_controller.dispose()
        event.accept()
