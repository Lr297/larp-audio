"""Read-only Qt model for canonical subtitle blocks."""

from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from larp_audio_mvp.core.contracts import SubtitleBlock, SubtitleDocument
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing


def _seconds(samples: int, sample_rate: int) -> str:
    total_ms = samples * 1_000 // sample_rate
    minutes, remainder = divmod(total_ms, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _decimal(value: Fraction, places: int = 2) -> str:
    with localcontext() as context:
        context.prec = 18
        number = Decimal(value.numerator) / Decimal(value.denominator)
    return f"{number:.{places}f}"


class SubtitleBlockTableModel(QAbstractTableModel):
    HEADERS = ("Block", "Time", "Text", "Words", "CPS", "Warning")

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._blocks: tuple[SubtitleBlock, ...] = ()
        self._sample_rate = 1
        self._display_ends: tuple[int, ...] = ()
        self._active_block_index: int | None = None

    def set_document(
        self,
        document: SubtitleDocument | tuple[SubtitleBlock, ...],
        sample_rate: int | None = None,
    ) -> None:
        self.beginResetModel()
        if isinstance(document, SubtitleDocument):
            self._blocks = document.blocks
            self._sample_rate = document.sample_rate
            self._display_ends = tuple(
                interval.display_end_sample
                for interval in apply_gapless_display_timing(document)
            )
        else:
            # Compatibility for an empty/reset model and old tests. Production
            # result rendering always passes the full canonical document.
            self._blocks = document
            self._sample_rate = sample_rate or 1
            self._display_ends = tuple(
                document[index + 1].cleaned_start_sample
                if index + 1 < len(document)
                else block.cleaned_end_sample
                for index, block in enumerate(document)
            )
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._blocks)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._blocks):
            return None
        block = self._blocks[index.row()]
        values = (
            block.block_index,
            f"{_seconds(block.cleaned_start_sample, self._sample_rate)} – {_seconds(self._display_ends[index.row()], self._sample_rate)}",
            "\n".join(block.display_lines),
            block.word_count,
            _decimal(block.characters_per_second),
            "Warning" if block.warnings else "—",
        )
        if role == Qt.DisplayRole:
            return values[index.column()]
        if role == Qt.ToolTipRole:
            if index.column() == 2:
                return block.display_text
            if index.column() == 5:
                return "\n".join(block.warnings) or "No warnings"
        if role == Qt.BackgroundRole and block.block_index == self._active_block_index:
            return QColor(255, 63, 61, 24)
        if role == Qt.ForegroundRole and block.warnings:
            return QColor("#FFD37A")
        if role == Qt.TextAlignmentRole and index.column() != 2:
            return int(Qt.AlignVCenter | Qt.AlignLeft)
        return None

    def block_at(self, row: int) -> SubtitleBlock | None:
        return self._blocks[row] if 0 <= row < len(self._blocks) else None

    def set_active_block(self, block_index: int | None) -> None:
        if block_index == self._active_block_index:
            return
        previous = self._active_block_index; self._active_block_index = block_index
        for value in (previous, block_index):
            if value is not None and 1 <= value <= len(self._blocks):
                self.dataChanged.emit(self.index(value - 1, 0), self.index(value - 1, self.columnCount() - 1), [Qt.BackgroundRole])


class WarningFilterProxyModel(QSortFilterProxyModel):
    """View-only warning filter; the canonical SubtitleDocument is untouched."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._warnings_only = False

    @property
    def warnings_only(self) -> bool:
        return self._warnings_only

    def set_warnings_only(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._warnings_only:
            return
        self._warnings_only = enabled
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        if not self._warnings_only:
            return True
        source = self.sourceModel()
        if not isinstance(source, SubtitleBlockTableModel):
            return False
        block = source.block_at(source_row)
        return bool(
            block
            and (
                block.warnings
                or block.contains_interpolated_words
                or block.contains_unresolved_words
            )
        )
