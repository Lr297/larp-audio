from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from larp_audio_mvp.gui.controller import GuiController
from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.gui.presets import PAUSE_PRESETS, PauseStylePreset
from larp_audio_mvp.gui.state import AudioPreflightRequest, AudioPreflightResult, GuiPhase
from larp_audio_mvp.pipeline.contracts import PipelineProgress, PipelineStage
from tests.gui.test_preview import FakeMediaBackend
from tests.pipeline.fakes import audio_info
from tests.pipeline.test_full_pipeline import write_wav


def _window(qapp, tmp_path: Path, **kwargs) -> MainWindow:
    window = MainWindow(settings=QSettings(str(tmp_path / "stage121.ini"), QSettings.IniFormat), media_backend_factory=kwargs.pop("media_backend_factory", FakeMediaBackend), **kwargs)
    window.show(); qapp.processEvents(); return window


def _visible_button_texts(window: MainWindow) -> set[str]:
    return {button.text() for button in window.findChildren(QPushButton) if button.isVisible()}


def test_one_page_client_copy_and_empty_state(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    texts = _visible_button_texts(window)
    assert {"Upload audio", "Upload script", "Process", "Start over", "Advanced Settings"}.issubset(texts)
    assert not {"Browse Audio…", "Load UTF-8 TXT…", "Create Subtitle Package", "Empty"} & texts
    assert window.pause_style is PauseStylePreset.BALANCED
    assert window.pause_preset_buttons["balanced"].isChecked()
    assert window.empty_hint.isVisible() and not window.result_tabs.isVisible()
    assert window.script_editor.minimumHeight() >= 220
    window.close()


def test_approved_editorial_hierarchy_is_the_production_composition(
    qapp, tmp_path: Path
) -> None:
    window = _window(qapp, tmp_path)
    strip = window.findChild(QLabel, "workflowStrip")
    assert strip is not None
    assert strip.text() == "AUDIO   /   SCRIPT   /   PROCESS   /   REVIEW"
    assert len(window.findChildren(QFrame, "surfaceCard")) == 2
    assert len(
        [
            button
            for button in window.findChildren(QPushButton)
            if button.isVisible() and button.text() == "Advanced Settings"
        ]
    ) == 1
    assert window.pause_preset_buttons["balanced"].isChecked()
    assert window.start_over_button.y() < window.full_input_panel.y()
    window.close()


def test_pause_presets_have_exact_central_mapping_and_custom_state(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    for preset in (PauseStylePreset.TIGHT, PauseStylePreset.BALANCED, PauseStylePreset.NATURAL):
        window.set_pause_preset(preset); expected = PAUSE_PRESETS[preset]
        assert Decimal(str(window.pause_threshold.value())) == expected.silence_threshold_db
        assert window.minimum_detected_silence.value() == expected.minimum_detected_silence_ms
        assert window.minimum_pause_to_shorten.value() == expected.minimum_pause_to_shorten_ms
        assert window.retained_pause.value() == expected.retained_pause_ms
        assert window.maximum_pause_removal.value() == expected.maximum_removed_per_pause_ms
        assert window.pause_style is preset
    window.retained_pause.setValue(333)
    assert window.pause_style is PauseStylePreset.CUSTOM
    assert window.custom_preset_label.isVisible()
    window.restore_all_defaults(); assert window.pause_style is PauseStylePreset.BALANCED
    window.close()


def test_exact_values_exist_only_in_closed_advanced_dialog(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    assert not window.advanced_dialog.isVisible()
    for control in (window.pause_threshold, window.minimum_detected_silence, window.retained_pause, window.compute_type, window.recognition_beam_size):
        assert not control.isVisible()
    window.advanced_settings_button.click(); qapp.processEvents()
    assert window.advanced_dialog.isVisible()
    assert window.pause_threshold.isVisible() and window.pause_threshold.suffix() == " dB"
    assert window.minimum_detected_silence.isVisible() and window.minimum_detected_silence.suffix() == " ms"
    window.advanced_dialog.close(); qapp.processEvents(); assert not window.advanced_dialog.isVisible()
    window.close()


def test_audio_upload_replace_remove_copy(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path); audio = tmp_path / "very long voiceover filename.wav"; write_wav(audio)
    identity = str(audio.resolve()); request = AudioPreflightRequest("audio", audio, identity, 1)
    window.controller.begin_audio_preflight(request); window.controller.apply_audio_preflight_result(AudioPreflightResult("audio", audio, identity, audio_info(audio)))
    assert window.browse_audio_button.text() == "Replace"
    assert window.audio_value.text() == audio.name
    assert window.audio_value.toolTip() == str(audio)
    assert window.remove_audio_button.isVisible()
    window.remove_audio_button.click(); qapp.processEvents()
    assert window.controller.state.source_audio_path is None
    assert window.browse_audio_button.text() == "Upload audio"
    window.close()


def test_initial_volume_is_applied_to_backend(qapp, tmp_path: Path) -> None:
    backend = FakeMediaBackend(); window = _window(qapp, tmp_path, media_backend_factory=lambda: backend)
    assert backend.volume == 80
    assert window.preview_panel.volume_slider.value() == 80
    window.close()


def test_start_over_preserves_global_model_and_output(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path); model = tmp_path / "model"; model.mkdir(); output = tmp_path / "output"; output.mkdir()
    window.controller.set_local_model(model); window.controller.set_output_directory(output); window.script_editor.setPlainText("Exact script text")
    audio = tmp_path / "audio.wav"; write_wav(audio); window.controller.set_source_audio(audio)
    window.set_pause_preset(PauseStylePreset.TIGHT); window.start_over(); qapp.processEvents()
    state = window.controller.state
    assert state.source_audio_path is None and state.script_input is not None and state.pipeline_result is None
    assert state.script_input.exact_text == "Exact script text"
    assert window.script_editor.toPlainText() == "Exact script text"
    assert state.local_model_path == model and state.output_directory == output
    assert window.pause_style is PauseStylePreset.BALANCED
    window.close()


def test_processing_copy_and_no_horizontal_scroll_at_reference_sizes(qapp, tmp_path: Path) -> None:
    window = _window(qapp, tmp_path)
    progress = PipelineProgress(PipelineStage.RECOGNIZING_SPEECH, 8, 14, "technical")
    window.render_state(replace(window.controller.state, phase=GuiPhase.PROCESSING, task_active=True, pipeline_progress=progress))
    assert window.processing_card.isVisible()
    assert window.status_message.text() == "Recognizing speech · step 8 of 14"
    assert window.progress.maximum() == 14
    assert window.progress.value() == 7
    assert window.process_button.text() == "Processing…"
    for width, height in ((1100,760),(1280,800),(1280,900),(1440,900),(1600,1000)):
        window.resize(width,height); qapp.processEvents()
        assert window.main_scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert not window.main_scroll_area.horizontalScrollBar().isVisible()
        assert window.process_button.width() > 80 and window.about_button.width() > 40
    window.render_state(window.controller.state); window.close()


def test_active_cue_does_not_overwrite_user_selection(qapp, tmp_path: Path) -> None:
    from larp_audio_mvp.subtitles import read_subtitle_document
    document = read_subtitle_document(Path("examples/stage_9_1_example_subtitle_blocks.json"))
    window = _window(qapp, tmp_path); window.table_model.set_document(document.blocks, document.sample_rate)
    if len(document.blocks) < 2:
        window.close(); return
    window.subtitle_table.selectRow(1); selected = window.subtitle_table.currentIndex().row()
    window.table_model.set_active_block(1)
    assert window.subtitle_table.currentIndex().row() == selected
    assert window.table_model._active_block_index == 1
    window.close()


def test_approved_reference_palette_has_no_legacy_accent() -> None:
    from larp_audio_mvp.gui.design.stylesheet import STYLESHEET
    assert "#FF3F3D" in STYLESHEET and "#060606" in STYLESHEET
    assert "#D94A5D" not in STYLESHEET and "#080506" not in STYLESHEET
    assert not any(value in STYLESHEET.upper() for value in ("#7C5CFF", "#9278FF", "#8A6BFF", "#6046D6"))
