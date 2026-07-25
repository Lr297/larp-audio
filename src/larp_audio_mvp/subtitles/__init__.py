"""Script-preserving subtitle chunking and canonical JSON persistence."""

from typing import Any

from .chunker import DeterministicSubtitleChunker
from .display import subtitle_display_text
from .serialization import (
    read_subtitle_document,
    subtitle_document_from_dict,
    subtitle_document_to_dict,
    write_subtitle_document,
)
from .validation import (
    SUBTITLE_SCHEMA_VERSION,
    calculate_subtitle_diagnostics,
    validate_subtitle_document,
)
from .timing import (
    GaplessDisplayTiming,
    GaplessTimingMetrics,
    apply_gapless_display_timing,
    validate_gapless_display_timing,
)

__all__ = [
    "SUBTITLE_SCHEMA_VERSION",
    "DeterministicSubtitleChunker",
    "GaplessDisplayTiming",
    "GaplessTimingMetrics",
    "SubtitleGenerationService",
    "SubtitleGenerationSummary",
    "calculate_subtitle_diagnostics",
    "apply_gapless_display_timing",
    "read_subtitle_document",
    "subtitle_document_from_dict",
    "subtitle_document_to_dict",
    "validate_subtitle_document",
    "validate_gapless_display_timing",
    "subtitle_display_text",
    "write_subtitle_document",
]


def __getattr__(name: str) -> Any:
    """Expose orchestration lazily so the independent SRT adapter stays acyclic."""

    if name in {"SubtitleGenerationService", "SubtitleGenerationSummary"}:
        from .service import SubtitleGenerationService, SubtitleGenerationSummary

        return {
            "SubtitleGenerationService": SubtitleGenerationService,
            "SubtitleGenerationSummary": SubtitleGenerationSummary,
        }[name]
    raise AttributeError(name)
