"""Deterministic script-preserving script-to-ASR alignment."""

from larp_audio_mvp.alignment.engine import (
    AlignmentOperation,
    ScriptAsrAlignmentEngine,
    string_similarity,
)
from larp_audio_mvp.alignment.normalizer import comparison_key
from larp_audio_mvp.alignment.script import read_script
from larp_audio_mvp.alignment.serialization import (
    alignment_from_dict,
    alignment_to_dict,
    read_alignment,
    write_alignment_atomic,
)
from larp_audio_mvp.alignment.service import ScriptAlignmentService, align_files
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.alignment.validation import (
    ALIGNMENT_SCHEMA_VERSION,
    calculate_alignment_diagnostics,
    validate_alignment_result,
)

__all__ = [
    "AlignmentOperation",
    "ALIGNMENT_SCHEMA_VERSION",
    "ScriptAlignmentService",
    "ScriptAsrAlignmentEngine",
    "align_files",
    "alignment_from_dict",
    "alignment_to_dict",
    "comparison_key",
    "calculate_alignment_diagnostics",
    "read_alignment",
    "read_script",
    "string_similarity",
    "tokenize_script",
    "validate_alignment_result",
    "write_alignment_atomic",
]
