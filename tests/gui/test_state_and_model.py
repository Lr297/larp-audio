from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from larp_audio_mvp.alignment import read_alignment
from larp_audio_mvp.gui.models import SubtitleBlockTableModel
from larp_audio_mvp.gui.state import GuiPhase, GuiState, summarize_alignment
from larp_audio_mvp.subtitles import read_subtitle_document


def test_state_defaults_are_explicit() -> None:
    state = GuiState()
    assert state.phase is GuiPhase.EMPTY
    assert not state.processing
    assert state.alignment is None


def test_alignment_summary_uses_strict_contract() -> None:
    alignment = read_alignment(Path("examples/stage_9_1_example_alignment.json"))
    summary = summarize_alignment(alignment)
    assert summary.schema_version == "alignment.schema.v2"
    assert summary.script_word_count == len(alignment.aligned_words)
    assert summary.asr_word_count == len(alignment.recognition.words)
    assert summary.provenance_complete


def test_subtitle_table_model_is_read_only(qapp) -> None:
    document = read_subtitle_document(
        Path("examples/stage_9_1_example_subtitle_blocks.json")
    )
    model = SubtitleBlockTableModel()
    model.set_document(document)
    assert model.rowCount() == len(document.blocks)
    assert model.columnCount() == 6
    assert model.data(model.index(0, 2), Qt.DisplayRole)
    assert model.data(model.index(0, 2), Qt.ToolTipRole)
    assert not (model.flags(model.index(0, 4)) & Qt.ItemIsEditable)
