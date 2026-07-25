"""Immutable domain contracts shared by pipeline ports.

The module contains data shape and local scalar invariants only. It deliberately
does not implement audio processing, alignment, chunking, or serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from math import isfinite
from pathlib import Path, PurePosixPath


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    SUCCESS_WITH_WARNINGS = "success_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EditKind(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


class AlignmentStatus(StrEnum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    MANY_TO_MANY = "many_to_many"
    SUBSTITUTION = "substitution"
    OMISSION = "omission"
    INSERTION = "insertion"
    REPETITION = "repetition"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ScriptTokenKind(StrEnum):
    WORD = "word"
    PUNCTUATION = "punctuation"
    WHITESPACE = "whitespace"


class AlignmentMatchType(StrEnum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    FUZZY = "fuzzy"
    ONE_SCRIPT_TO_MANY_ASR = "one_script_to_many_asr"
    MANY_SCRIPT_TO_ONE_ASR = "many_script_to_one_asr"
    SUBSTITUTION = "substitution"
    INTERPOLATED = "interpolated"
    UNRESOLVED = "unresolved"


class TimingStatus(StrEnum):
    OBSERVED = "observed"
    DISTRIBUTED = "distributed"
    INTERPOLATED = "interpolated"
    UNRESOLVED = "unresolved"


class SubtitleTimingProvenance(StrEnum):
    """Block-level summary of the word timing evidence it contains."""

    OBSERVED = "observed"
    MIXED_OBSERVED_INTERPOLATED = "mixed_observed_interpolated"
    INTERPOLATED = "interpolated"
    ANCHORED_WITH_UNRESOLVED = "anchored_with_unresolved"


@dataclass(frozen=True, slots=True)
class SampleRange:
    """Half-open sample range ``[start, end)``."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("sample range start must be non-negative")
        if self.end < self.start:
            raise ValueError("sample range end must not precede start")


@dataclass(frozen=True, slots=True)
class InputProject:
    """Immutable user inputs and output destination for one local job."""

    project_id: str
    audio_path: Path
    script_text: str
    output_directory: Path
    script_path: Path | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty")
        if not self.script_text.strip():
            raise ValueError("script_text must not be empty")


@dataclass(frozen=True, slots=True)
class AudioInfo:
    """Probed audio metadata expressed on the source sample timeline."""

    source_path: Path
    sample_rate: int
    channels: int
    sample_format: str | None
    total_samples: int | None
    sha256: str | None = None
    format_name: str | None = None
    format_long_name: str | None = None
    codec_name: str | None = None
    duration_seconds: Fraction | None = None
    duration_source: str | None = None
    bit_depth: int | None = None
    file_size_bytes: int | None = None
    stream_index: int | None = None
    is_canonical: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.sample_format is not None and not self.sample_format:
            raise ValueError("sample_format must be non-empty when provided")
        if self.total_samples is not None and self.total_samples < 0:
            raise ValueError("total_samples must be non-negative")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        if self.bit_depth is not None and self.bit_depth <= 0:
            raise ValueError("bit_depth must be positive when provided")
        if self.file_size_bytes is not None and self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must be non-negative")
        if self.stream_index is not None and self.stream_index < 0:
            raise ValueError("stream_index must be non-negative")


@dataclass(frozen=True, slots=True)
class WordTimestamp:
    """Internal ASR timing observation.

    ``recognized_text`` is matching evidence only and must never be used as
    displayed subtitle text.
    """

    recognized_text: str
    sample_range: SampleRange
    confidence: float | None = None
    provenance: str = "observed"

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.provenance:
            raise ValueError("provenance must not be empty")


@dataclass(frozen=True, slots=True)
class RecognizedWord:
    """One local STT observation on cleaned and original timelines.

    ``text`` is recognition evidence only. It is never an allowed source for
    displayed subtitles. Integer sample indices are authoritative; all second
    values are exact derived fractions.
    """

    text: str
    sample_rate: int
    start_sample_original: int
    end_sample_original: int
    start_sample_cleaned: int
    end_sample_cleaned: int
    confidence: float | None = None
    start_seconds: Fraction = field(init=False)
    end_seconds: Fraction = field(init=False)
    start_seconds_original: Fraction = field(init=False)
    end_seconds_original: Fraction = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or self.text == "":
            raise ValueError("recognized word text must not be empty")
        for name in (
            "sample_rate",
            "start_sample_original",
            "end_sample_original",
            "start_sample_cleaned",
            "end_sample_cleaned",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.sample_rate <= 0:
            raise ValueError("recognized word sample_rate must be positive")
        if self.start_sample_cleaned < 0:
            raise ValueError("cleaned word start must be non-negative")
        if self.end_sample_cleaned <= self.start_sample_cleaned:
            raise ValueError("cleaned word interval must be positive")
        if self.start_sample_original < 0:
            raise ValueError("original word start must be non-negative")
        if self.end_sample_original <= self.start_sample_original:
            raise ValueError("original word interval must be positive")
        if self.confidence is not None and (
            not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confidence must be finite and between 0 and 1")

        object.__setattr__(
            self,
            "start_seconds",
            Fraction(self.start_sample_cleaned, self.sample_rate),
        )
        object.__setattr__(
            self,
            "end_seconds",
            Fraction(self.end_sample_cleaned, self.sample_rate),
        )
        object.__setattr__(
            self,
            "start_seconds_original",
            Fraction(self.start_sample_original, self.sample_rate),
        )
        object.__setattr__(
            self,
            "end_seconds_original",
            Fraction(self.end_sample_original, self.sample_rate),
        )


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """Versioned local STT result containing timing evidence only."""

    schema_version: str
    backend: str
    model: str
    language: str | None
    sample_rate: int
    duration_samples_cleaned: int
    duration_samples_original: int
    words: tuple[RecognizedWord, ...] = field(default_factory=tuple)
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    duration: Fraction = field(init=False)
    duration_original: Fraction = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("recognition schema_version must not be empty")
        if not self.backend or not self.model:
            raise ValueError("recognition backend and model must not be empty")
        if self.language is not None and not self.language:
            raise ValueError("recognition language must not be empty")
        for name in (
            "sample_rate",
            "duration_samples_cleaned",
            "duration_samples_original",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.sample_rate <= 0:
            raise ValueError("recognition sample_rate must be positive")
        if self.duration_samples_cleaned <= 0:
            raise ValueError("cleaned recognition duration must be positive")
        if self.duration_samples_original < self.duration_samples_cleaned:
            raise ValueError("original duration must not be shorter than cleaned")

        metadata_keys = tuple(key for key, _ in self.metadata)
        if metadata_keys != tuple(sorted(metadata_keys)):
            raise ValueError("recognition metadata must be sorted by key")
        if len(metadata_keys) != len(set(metadata_keys)):
            raise ValueError("recognition metadata keys must be unique")
        if any(not key or not value for key, value in self.metadata):
            raise ValueError("recognition metadata keys and values must not be empty")

        previous_cleaned_start = -1
        previous_cleaned_end = -1
        previous_original_start = -1
        previous_original_end = -1
        for word in self.words:
            if word.sample_rate != self.sample_rate:
                raise ValueError("recognized word sample rate mismatch")
            if word.end_sample_cleaned > self.duration_samples_cleaned:
                raise ValueError("recognized word exceeds cleaned duration")
            if word.end_sample_original > self.duration_samples_original:
                raise ValueError("recognized word exceeds original duration")
            if (
                word.start_sample_cleaned < previous_cleaned_start
                or word.end_sample_cleaned < previous_cleaned_end
                or word.start_sample_original < previous_original_start
                or word.end_sample_original < previous_original_end
            ):
                raise ValueError("recognized word timestamps must be monotonic")
            previous_cleaned_start = word.start_sample_cleaned
            previous_cleaned_end = word.end_sample_cleaned
            previous_original_start = word.start_sample_original
            previous_original_end = word.end_sample_original

        object.__setattr__(
            self,
            "duration",
            Fraction(self.duration_samples_cleaned, self.sample_rate),
        )
        object.__setattr__(
            self,
            "duration_original",
            Fraction(self.duration_samples_original, self.sample_rate),
        )


@dataclass(frozen=True, slots=True)
class ScriptDocument:
    """Exact decoded UTF-8 script plus byte-level source provenance."""

    exact_text: str
    source_path: Path
    source_sha256: str
    encoding: str
    has_bom: bool
    character_count: int
    line_count: int
    source_kind: str | None = None
    newline_style: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.exact_text, str):
            raise TypeError("script exact_text must be a string")
        if not self.source_sha256:
            raise ValueError("script source_sha256 must not be empty")
        if self.encoding != "utf-8":
            raise ValueError("script encoding must be utf-8")
        if not isinstance(self.has_bom, bool):
            raise TypeError("script has_bom must be boolean")
        if self.character_count != len(self.exact_text):
            raise ValueError("script character_count does not match exact_text")
        if self.character_count < 0 or self.line_count < 0:
            raise ValueError("script counts must be non-negative")
        if self.source_kind is not None and not self.source_kind:
            raise ValueError("script source_kind must be non-empty when provided")
        if self.newline_style is not None and not self.newline_style:
            raise ValueError("script newline_style must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class ScriptToken:
    """One reversible token with exact source character offsets."""

    token_index: int
    kind: ScriptTokenKind
    exact_text: str
    char_start: int
    char_end: int
    comparison_key: str | None = None

    def __post_init__(self) -> None:
        if self.token_index < 0:
            raise ValueError("token_index must be non-negative")
        if not self.exact_text:
            raise ValueError("script token exact_text must not be empty")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("script token character interval must be positive")
        if self.kind is ScriptTokenKind.WORD:
            if not self.comparison_key:
                raise ValueError("word tokens require a comparison key")
        elif self.comparison_key is not None:
            raise ValueError("non-word tokens must not contain a comparison key")


@dataclass(frozen=True, slots=True)
class AlignedScriptWord:
    """Exact original-script word with optional dual-timeline timing."""

    script_word_index: int
    token_index: int
    exact_text: str
    char_start: int
    char_end: int
    cleaned_start_sample: int | None
    cleaned_end_sample: int | None
    original_start_sample: int | None
    original_end_sample: int | None
    timing_status: TimingStatus
    match_type: AlignmentMatchType
    matched_recognition_indices: tuple[int, ...] = field(default_factory=tuple)
    alignment_operation_id: str | None = None
    interpolation_left_anchor_script_word_index: int | None = None
    interpolation_right_anchor_script_word_index: int | None = None
    text_similarity: Fraction | None = None
    alignment_score: Fraction | None = None
    asr_confidence: float | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.script_word_index < 0 or self.token_index < 0:
            raise ValueError("aligned script indices must be non-negative")
        if not self.exact_text:
            raise ValueError("aligned script exact_text must not be empty")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("aligned script character interval must be positive")
        if self.matched_recognition_indices != tuple(
            sorted(set(self.matched_recognition_indices))
        ) or any(index < 0 for index in self.matched_recognition_indices):
            raise ValueError("matched recognition indices must be unique and sorted")
        if self.alignment_operation_id is not None and not self.alignment_operation_id:
            raise ValueError("alignment operation id must not be blank")
        for name in (
            "interpolation_left_anchor_script_word_index",
            "interpolation_right_anchor_script_word_index",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or null")
        for name in ("text_similarity", "alignment_score"):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.asr_confidence is not None and (
            not isfinite(self.asr_confidence)
            or not 0 <= self.asr_confidence <= 1
        ):
            raise ValueError("asr_confidence must be finite and in [0, 1]")

        timing_values = (
            self.cleaned_start_sample,
            self.cleaned_end_sample,
            self.original_start_sample,
            self.original_end_sample,
        )
        if self.timing_status is TimingStatus.UNRESOLVED:
            if any(value is not None for value in timing_values):
                raise ValueError("unresolved timing must not contain sample bounds")
        else:
            if any(value is None for value in timing_values):
                raise ValueError("resolved timing requires both timeline bounds")
            assert self.cleaned_start_sample is not None
            assert self.cleaned_end_sample is not None
            assert self.original_start_sample is not None
            assert self.original_end_sample is not None
            if (
                self.cleaned_start_sample < 0
                or self.cleaned_end_sample <= self.cleaned_start_sample
                or self.original_start_sample < 0
                or self.original_end_sample <= self.original_start_sample
            ):
                raise ValueError("resolved timing intervals must be positive")
        if self.match_type is AlignmentMatchType.INTERPOLATED and (
            self.timing_status is not TimingStatus.INTERPOLATED
        ):
            raise ValueError("interpolated match requires interpolated timing")
        if self.timing_status is TimingStatus.INTERPOLATED and (
            self.match_type is not AlignmentMatchType.INTERPOLATED
        ):
            raise ValueError("interpolated timing requires interpolated match")
        if self.timing_status is TimingStatus.INTERPOLATED:
            if self.matched_recognition_indices:
                raise ValueError("interpolated timing cannot claim matched ASR evidence")
            if self.asr_confidence is not None:
                raise ValueError("interpolated timing cannot contain ASR confidence")
            if self.alignment_operation_id is not None:
                raise ValueError("interpolated timing cannot claim an accepted operation")
            if self.text_similarity is not None or self.alignment_score is not None:
                raise ValueError("interpolated timing cannot claim accepted text scores")
            if (
                self.interpolation_left_anchor_script_word_index is None
                or self.interpolation_right_anchor_script_word_index is None
            ):
                raise ValueError("interpolated timing requires two script anchors")
        elif (
            self.interpolation_left_anchor_script_word_index is not None
            or self.interpolation_right_anchor_script_word_index is not None
        ):
            raise ValueError("only interpolated timing can contain interpolation anchors")
        if self.timing_status is TimingStatus.UNRESOLVED:
            if self.matched_recognition_indices:
                raise ValueError("unresolved timing cannot claim matched ASR evidence")
            if self.asr_confidence is not None:
                raise ValueError("unresolved timing cannot contain ASR confidence")
            if self.alignment_operation_id is not None:
                raise ValueError("unresolved timing cannot claim an accepted operation")
            if self.text_similarity is not None or self.alignment_score is not None:
                raise ValueError("unresolved timing cannot claim accepted text scores")


@dataclass(frozen=True, slots=True)
class RejectedAsrEvidence:
    """ASR observation considered by an operation but not accepted as a match."""

    recognition_index: int
    text: str
    cleaned_start_sample: int
    cleaned_end_sample: int
    original_start_sample: int
    original_end_sample: int
    confidence: float | None
    rejection_reason: str
    related_script_word_indices: tuple[int, ...]
    attempted_match_type: AlignmentMatchType
    attempted_operation_id: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.recognition_index, bool)
            or not isinstance(self.recognition_index, int)
            or self.recognition_index < 0
        ):
            raise ValueError("rejected ASR index must be non-negative")
        if not self.text or not self.rejection_reason or not self.attempted_operation_id:
            raise ValueError("rejected ASR provenance strings must not be empty")
        if self.related_script_word_indices != tuple(
            sorted(set(self.related_script_word_indices))
        ) or not self.related_script_word_indices:
            raise ValueError("rejected ASR script indices must be non-empty and sorted")
        if any(index < 0 for index in self.related_script_word_indices):
            raise ValueError("rejected ASR script indices must be non-negative")
        if (
            self.cleaned_start_sample < 0
            or self.cleaned_end_sample <= self.cleaned_start_sample
            or self.original_start_sample < 0
            or self.original_end_sample <= self.original_start_sample
        ):
            raise ValueError("rejected ASR intervals must be positive")
        if self.confidence is not None and (
            not isfinite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("rejected ASR confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class UnmatchedAsrWord:
    """ASR-only observation that must never become script/display text."""

    recognition_index: int
    text: str
    cleaned_start_sample: int
    cleaned_end_sample: int
    original_start_sample: int
    original_end_sample: int
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.recognition_index < 0 or not self.text:
            raise ValueError("unmatched ASR identity must be valid")
        if (
            self.cleaned_start_sample < 0
            or self.cleaned_end_sample <= self.cleaned_start_sample
            or self.original_start_sample < 0
            or self.original_end_sample <= self.original_start_sample
        ):
            raise ValueError("unmatched ASR intervals must be positive")
        if self.confidence is not None and (
            not isfinite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("unmatched ASR confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class AlignmentDiagnostics:
    total_script_words: int
    total_asr_words: int
    exact_matches: int
    normalized_matches: int
    fuzzy_matches: int
    split_merge_matches: int
    substitutions: int
    interpolated_words: int
    unresolved_script_words: int
    unmatched_asr_words: int
    rejected_asr_evidence_count: int
    classified_asr_words: int
    provenance_complete: bool
    observed_timing_coverage: Fraction
    total_timing_coverage: Fraction
    text_alignment_coverage: Fraction

    def __post_init__(self) -> None:
        for name in (
            "total_script_words",
            "total_asr_words",
            "exact_matches",
            "normalized_matches",
            "fuzzy_matches",
            "split_merge_matches",
            "substitutions",
            "interpolated_words",
            "unresolved_script_words",
            "unmatched_asr_words",
            "rejected_asr_evidence_count",
            "classified_asr_words",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.provenance_complete, bool):
            raise ValueError("provenance_complete must be boolean")
        for name in (
            "observed_timing_coverage",
            "total_timing_coverage",
            "text_alignment_coverage",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """Versioned script-preserving script-to-ASR alignment result."""

    schema_version: str
    script: ScriptDocument
    recognition: RecognitionResult
    edit_map: EditMap
    sample_rate: int
    tokens: tuple[ScriptToken, ...]
    aligned_words: tuple[AlignedScriptWord, ...]
    unmatched_asr_words: tuple[UnmatchedAsrWord, ...]
    rejected_asr_evidence: tuple[RejectedAsrEvidence, ...]
    diagnostics: AlignmentDiagnostics
    configuration_snapshot: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.schema_version != "alignment.schema.v2":
            raise ValueError("alignment schema_version must be alignment.schema.v2")
        if self.sample_rate <= 0:
            raise ValueError("alignment sample_rate must be positive")
        if "".join(token.exact_text for token in self.tokens) != self.script.exact_text:
            raise ValueError("alignment tokens do not reconstruct exact script")
        cursor = 0
        for expected_index, token in enumerate(self.tokens):
            if token.token_index != expected_index or token.char_start != cursor:
                raise ValueError("alignment tokens are not contiguous and indexed")
            if self.script.exact_text[token.char_start : token.char_end] != token.exact_text:
                raise ValueError("alignment token does not match exact script span")
            cursor = token.char_end
        if cursor != len(self.script.exact_text):
            raise ValueError("alignment tokens do not cover exact script")
        word_tokens = tuple(
            token for token in self.tokens if token.kind is ScriptTokenKind.WORD
        )
        if len(word_tokens) != len(self.aligned_words):
            raise ValueError("every script word token requires one alignment record")
        for word_index, (token, aligned) in enumerate(
            zip(word_tokens, self.aligned_words)
        ):
            if (
                aligned.script_word_index != word_index
                or aligned.token_index != token.token_index
                or aligned.exact_text != token.exact_text
                or aligned.char_start != token.char_start
                or aligned.char_end != token.char_end
            ):
                raise ValueError("aligned word does not reference its exact token")
        if self.diagnostics.total_script_words != len(self.aligned_words):
            raise ValueError("diagnostic script-word total is inconsistent")
        if self.diagnostics.total_asr_words != len(self.recognition.words):
            raise ValueError("diagnostic ASR-word total is inconsistent")
        if self.diagnostics.unmatched_asr_words != len(self.unmatched_asr_words):
            raise ValueError("diagnostic unmatched-ASR total is inconsistent")
        previous_cleaned_end = -1
        previous_original_end = -1
        for aligned in self.aligned_words:
            if any(
                index >= len(self.recognition.words)
                for index in aligned.matched_recognition_indices
            ):
                raise ValueError("aligned word references absent recognition word")
            if aligned.cleaned_start_sample is None:
                continue
            assert aligned.cleaned_end_sample is not None
            assert aligned.original_start_sample is not None
            assert aligned.original_end_sample is not None
            if (
                aligned.cleaned_end_sample > self.edit_map.output_total_samples
                or aligned.original_end_sample > self.edit_map.source_total_samples
                or aligned.cleaned_start_sample < previous_cleaned_end
                or aligned.original_start_sample < previous_original_end
            ):
                raise ValueError("aligned word timing is out of bounds or overlapping")
            previous_cleaned_end = aligned.cleaned_end_sample
            previous_original_end = aligned.original_end_sample
        unmatched_indices = tuple(
            word.recognition_index for word in self.unmatched_asr_words
        )
        if unmatched_indices != tuple(sorted(set(unmatched_indices))):
            raise ValueError("unmatched ASR indices must be sorted and unique")
        if any(index >= len(self.recognition.words) for index in unmatched_indices):
            raise ValueError("unmatched ASR word references absent recognition word")
        rejected_indices = tuple(
            evidence.recognition_index for evidence in self.rejected_asr_evidence
        )
        if rejected_indices != tuple(sorted(set(rejected_indices))):
            raise ValueError("rejected ASR indices must be sorted and unique")
        if any(index >= len(self.recognition.words) for index in rejected_indices):
            raise ValueError("rejected ASR evidence references absent recognition word")
        if self.diagnostics.rejected_asr_evidence_count != len(
            self.rejected_asr_evidence
        ):
            raise ValueError("diagnostic rejected-ASR total is inconsistent")
        config_keys = tuple(key for key, _ in self.configuration_snapshot)
        if config_keys != tuple(sorted(config_keys)) or len(config_keys) != len(
            set(config_keys)
        ):
            raise ValueError("alignment configuration snapshot must be sorted")


@dataclass(frozen=True, slots=True)
class PauseCandidate:
    """A possible pause detected on the source sample timeline."""

    sample_range: SampleRange
    confidence: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PauseSegment:
    """Detected half-open silence interval on an exact sample timeline.

    Seconds are derived values stored as :class:`Fraction`; sample indices are
    the only source of truth.
    """

    start_sample: int
    end_sample: int
    sample_rate: int
    length_samples: int = field(init=False)
    start_seconds: Fraction = field(init=False)
    end_seconds: Fraction = field(init=False)
    duration_seconds: Fraction = field(init=False)

    def __post_init__(self) -> None:
        for name in ("start_sample", "end_sample", "sample_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.start_sample < 0:
            raise ValueError("pause start_sample must be non-negative")
        if self.end_sample <= self.start_sample:
            raise ValueError("pause end_sample must be greater than start_sample")
        if self.sample_rate <= 0:
            raise ValueError("pause sample_rate must be positive")

        length_samples = self.end_sample - self.start_sample
        object.__setattr__(self, "length_samples", length_samples)
        object.__setattr__(
            self, "start_seconds", Fraction(self.start_sample, self.sample_rate)
        )
        object.__setattr__(
            self, "end_seconds", Fraction(self.end_sample, self.sample_rate)
        )
        object.__setattr__(
            self, "duration_seconds", Fraction(length_samples, self.sample_rate)
        )


@dataclass(frozen=True, slots=True)
class PauseShorteningDecision:
    """One immutable keep/shorten policy decision for a detected pause."""

    pause: PauseSegment
    remove_range: SampleRange | None
    reason: str
    retained_before_samples: int = 0
    retained_after_samples: int = 0

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("pause decision reason must not be empty")
        for name in ("retained_before_samples", "retained_after_samples"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.remove_range is None:
            if self.retained_before_samples or self.retained_after_samples:
                raise ValueError("unchanged pauses must not contain retained splits")
            return
        if (
            self.remove_range.start < self.pause.start_sample
            or self.remove_range.end > self.pause.end_sample
            or self.remove_range.end <= self.remove_range.start
        ):
            raise ValueError("removed range must be a non-empty part of the pause")
        if (
            self.retained_before_samples
            != self.remove_range.start - self.pause.start_sample
            or self.retained_after_samples
            != self.pause.end_sample - self.remove_range.end
        ):
            raise ValueError("retained split must exactly cover the pause boundaries")

    @property
    def shortened(self) -> bool:
        return self.remove_range is not None


@dataclass(frozen=True, slots=True)
class EditSpan:
    """One keep/remove decision in a versioned edit map."""

    kind: EditKind
    source_range: SampleRange
    output_range: SampleRange | None = None
    reason: str = ""
    target_anchor: int | None = None
    candidate_range: SampleRange | None = None
    retained_before_samples: int = 0
    retained_after_samples: int = 0

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("edit span reason must not be empty")
        if self.kind is EditKind.KEEP:
            if self.output_range is None:
                raise ValueError("kept spans require an output range")
            if self.target_anchor is not None:
                raise ValueError("kept spans must not use a target anchor")
            if self.output_range.end - self.output_range.start != (
                self.source_range.end - self.source_range.start
            ):
                raise ValueError("kept spans must preserve their sample length")
            if self.candidate_range is not None:
                raise ValueError("kept spans must not contain a pause candidate")
            if self.retained_before_samples or self.retained_after_samples:
                raise ValueError("kept spans must not contain retained pause samples")
            return
        if self.kind is not EditKind.REMOVE:
            raise ValueError(f"unsupported edit kind: {self.kind}")
        if self.output_range is not None:
            raise ValueError("removed spans must not fabricate an output range")
        if self.target_anchor is None or self.target_anchor < 0:
            raise ValueError("removed spans require a non-negative target anchor")
        if self.candidate_range is None:
            raise ValueError("removed spans require their candidate pause range")
        if (
            self.candidate_range.start + self.retained_before_samples
            != self.source_range.start
            or self.source_range.end + self.retained_after_samples
            != self.candidate_range.end
        ):
            raise ValueError("removed span and retained samples must cover candidate")
        if self.retained_before_samples <= 0 or self.retained_after_samples <= 0:
            raise ValueError("removed pauses must retain samples on both sides")

    @property
    def source_start(self) -> int:
        return self.source_range.start

    @property
    def source_end(self) -> int:
        return self.source_range.end

    @property
    def target_start(self) -> int:
        if self.output_range is not None:
            return self.output_range.start
        assert self.target_anchor is not None
        return self.target_anchor

    @property
    def target_end(self) -> int:
        if self.output_range is not None:
            return self.output_range.end
        assert self.target_anchor is not None
        return self.target_anchor

    @property
    def removed_samples(self) -> int:
        if self.kind is EditKind.REMOVE:
            return self.source_range.end - self.source_range.start
        return 0


@dataclass(frozen=True, slots=True)
class EditMap:
    """Versioned source-to-cleaned timeline contract."""

    schema_version: str
    policy_version: str
    sample_rate: int
    source_total_samples: int
    output_total_samples: int
    source_sha256: str
    spans: tuple[EditSpan, ...] = field(default_factory=tuple)
    output_sha256: str | None = None
    policy_snapshot: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("schema_version must not be empty")
        if not self.policy_version:
            raise ValueError("policy_version must not be empty")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.source_total_samples < 0 or self.output_total_samples < 0:
            raise ValueError("sample totals must be non-negative")
        if not self.source_sha256:
            raise ValueError("source_sha256 must not be empty")
        _validate_edit_map_spans(self)

    @property
    def removed_samples(self) -> int:
        return self.source_total_samples - self.output_total_samples


AlignedWord = AlignedScriptWord
"""Deprecated compatibility alias; use :class:`AlignedScriptWord`."""


@dataclass(frozen=True, slots=True)
class SubtitleBlock:
    """Canonical display block linked to one exact original-script span."""

    block_index: int
    source_char_start: int
    source_char_end: int
    source_text_exact: str
    display_lines: tuple[str, ...]
    first_token_index: int
    last_token_index: int
    script_word_indices: tuple[int, ...]
    interpolated_script_word_indices: tuple[int, ...]
    unresolved_script_word_indices: tuple[int, ...]
    cleaned_start_sample: int
    cleaned_end_sample: int
    original_start_sample: int
    original_end_sample: int
    duration_samples: int
    word_count: int
    visible_character_count: int
    characters_per_second: Fraction
    timing_provenance: SubtitleTimingProvenance
    contains_interpolated_words: bool
    contains_unresolved_words: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.block_index < 1:
            raise ValueError("subtitle block_index must start at 1")
        if self.source_char_start < 0 or self.source_char_end <= self.source_char_start:
            raise ValueError("invalid source character range")
        if not self.source_text_exact:
            raise ValueError("subtitle source_text_exact must not be empty")
        if not self.display_lines or any(not line for line in self.display_lines):
            raise ValueError("subtitle block requires at least one layout line")
        if self.first_token_index < 0 or self.last_token_index < self.first_token_index:
            raise ValueError("subtitle token range is invalid")
        if not self.script_word_indices:
            raise ValueError("subtitle block requires at least one script word")
        if self.script_word_indices != tuple(sorted(set(self.script_word_indices))):
            raise ValueError("subtitle script word indices must be sorted and unique")
        for name in (
            "interpolated_script_word_indices",
            "unresolved_script_word_indices",
        ):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))) or not set(values).issubset(
                self.script_word_indices
            ):
                raise ValueError(f"{name} must be a sorted subset of block words")
        if (
            self.cleaned_start_sample < 0
            or self.cleaned_end_sample <= self.cleaned_start_sample
            or self.original_start_sample < 0
            or self.original_end_sample <= self.original_start_sample
        ):
            raise ValueError("subtitle timing intervals must be positive")
        if self.duration_samples != self.cleaned_end_sample - self.cleaned_start_sample:
            raise ValueError("subtitle duration_samples is inconsistent")
        if self.word_count != len(self.script_word_indices):
            raise ValueError("subtitle word_count is inconsistent")
        if self.visible_character_count <= 0:
            raise ValueError("subtitle visible_character_count must be positive")
        if self.characters_per_second <= 0:
            raise ValueError("subtitle characters_per_second must be positive")
        if self.contains_interpolated_words != bool(
            self.interpolated_script_word_indices
        ):
            raise ValueError("subtitle interpolated flag is inconsistent")
        if self.contains_unresolved_words != bool(
            self.unresolved_script_word_indices
        ):
            raise ValueError("subtitle unresolved flag is inconsistent")

    @property
    def display_text(self) -> str:
        """Final user-visible text; source_text_exact remains untouched."""

        return " ".join(self.display_lines)

    @property
    def display_text_plain(self) -> str:
        """Canonical display text without the optional layout newline."""

        return " ".join(self.display_lines)

    @property
    def render_text(self) -> str:
        """Canonical Preview/SRT rendering with at most one layout newline."""

        return "\n".join(self.display_lines)


@dataclass(frozen=True, slots=True)
class SubtitleDiagnostics:
    total_blocks: int
    total_script_words: int
    exported_script_words: int
    unresolved_script_words: int
    attached_unresolved_words: int
    interpolated_script_words: int
    blocks_with_interpolated_words: int
    blocks_with_unresolved_words: int
    average_block_duration: Fraction
    maximum_block_duration: Fraction
    average_characters_per_second: Fraction
    maximum_characters_per_second: Fraction
    blocks_over_cps_limit: int
    blocks_over_duration_limit: int
    blocks_over_line_length_limit: int
    single_word_blocks: int
    short_blocks: int
    average_words_per_block: Fraction
    minimum_words_in_block: int
    maximum_words_in_block: int
    blocks_created_at_sentence_boundary: int
    blocks_created_at_comma_boundary: int
    blocks_created_at_gap_boundary: int
    blocks_forced_by_hard_limit: int
    text_coverage: Fraction
    timing_coverage: Fraction
    srt_exportable: bool
    warnings_count: int
    internal_gap_count: int = 0
    srt_gap_count: int = 0
    overlap_count: int = 0
    maximum_internal_gap_ms: int = 0
    maximum_srt_gap_ms: int = 0
    list_item_count: int = 0
    list_item_merge_violation_count: int = 0
    protected_unit_count: int = 0
    protected_unit_violation_count: int = 0
    adjective_noun_split_count: int = 0
    verb_object_split_count: int = 0
    phrasal_verb_split_count: int = 0
    preposition_object_split_count: int = 0
    number_unit_split_count: int = 0
    product_name_split_count: int = 0
    maximum_display_characters: int = 0
    orphan_fragment_count: int = 0
    incomplete_ending_count: int = 0
    trailing_period_violation_count: int = 0
    trailing_comma_violation_count: int = 0
    three_line_cue_count: int = 0
    empty_line_count: int = 0
    maximum_plain_characters: int = 0
    maximum_render_line_characters: int = 0
    cue_count: int = 0
    two_line_cue_count: int = 0
    forced_syntax_split_count: int = 0
    auxiliary_verb_split_count: int = 0
    verb_particle_split_count: int = 0
    compound_noun_split_count: int = 0
    degree_modifier_split_count: int = 0
    temporal_connector_split_count: int = 0
    proper_name_split_count: int = 0
    semantic_cue_count: int = 0
    unnecessary_split_count: int = 0
    required_boundary_miss_count: int = 0
    list_item_internal_split_count: int = 0
    orphan_beginning_count: int = 0
    wh_clause_split_count: int = 0
    or_not_split_count: int = 0
    parser_low_confidence_split_count: int = 0

    def __post_init__(self) -> None:
        for name in (
            "total_blocks",
            "total_script_words",
            "exported_script_words",
            "unresolved_script_words",
            "attached_unresolved_words",
            "interpolated_script_words",
            "blocks_with_interpolated_words",
            "blocks_with_unresolved_words",
            "blocks_over_cps_limit",
            "blocks_over_duration_limit",
            "blocks_over_line_length_limit",
            "single_word_blocks",
            "short_blocks",
            "minimum_words_in_block",
            "maximum_words_in_block",
            "blocks_created_at_sentence_boundary",
            "blocks_created_at_comma_boundary",
            "blocks_created_at_gap_boundary",
            "blocks_forced_by_hard_limit",
            "warnings_count",
            "internal_gap_count",
            "srt_gap_count",
            "overlap_count",
            "maximum_internal_gap_ms",
            "maximum_srt_gap_ms",
            "list_item_count",
            "list_item_merge_violation_count",
            "protected_unit_count",
            "protected_unit_violation_count",
            "adjective_noun_split_count",
            "verb_object_split_count",
            "phrasal_verb_split_count",
            "preposition_object_split_count",
            "number_unit_split_count",
            "product_name_split_count",
            "maximum_display_characters",
            "orphan_fragment_count",
            "incomplete_ending_count",
            "trailing_period_violation_count",
            "trailing_comma_violation_count",
            "three_line_cue_count",
            "empty_line_count",
            "maximum_plain_characters",
            "maximum_render_line_characters",
            "cue_count",
            "two_line_cue_count",
            "forced_syntax_split_count",
            "auxiliary_verb_split_count",
            "verb_particle_split_count",
            "compound_noun_split_count",
            "degree_modifier_split_count",
            "temporal_connector_split_count",
            "proper_name_split_count",
            "semantic_cue_count",
            "unnecessary_split_count",
            "required_boundary_miss_count",
            "list_item_internal_split_count",
            "orphan_beginning_count",
            "wh_clause_split_count",
            "or_not_split_count",
            "parser_low_confidence_split_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in (
            "average_block_duration",
            "maximum_block_duration",
            "average_characters_per_second",
            "maximum_characters_per_second",
            "average_words_per_block",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("text_coverage", "timing_coverage"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if not isinstance(self.srt_exportable, bool):
            raise ValueError("srt_exportable must be boolean")


@dataclass(frozen=True, slots=True)
class SubtitleDocument:
    """Versioned, script-preserving input to concrete subtitle exporters."""

    schema_version: str
    source_alignment_schema_version: str
    source_alignment_sha256: str
    script_sha256: str
    script_encoding: str
    script_has_bom: bool
    exact_script_text: str
    sample_rate: int
    cleaned_total_samples: int
    original_total_samples: int
    configuration_snapshot: tuple[tuple[str, str], ...]
    blocks: tuple[SubtitleBlock, ...]
    diagnostics: SubtitleDiagnostics
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.schema_version != "subtitle_blocks.schema.v1":
            raise ValueError("unsupported subtitle document schema")
        if self.source_alignment_schema_version != "alignment.schema.v2":
            raise ValueError("subtitle document requires alignment.schema.v2")
        for name in ("source_alignment_sha256", "script_sha256"):
            value = getattr(self, name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if self.script_encoding != "utf-8" or not isinstance(self.script_has_bom, bool):
            raise ValueError("subtitle script encoding metadata is invalid")
        if not self.exact_script_text or not self.exact_script_text.strip():
            raise ValueError("subtitle exact script text must contain visible text")
        if self.sample_rate <= 0:
            raise ValueError("subtitle sample_rate must be positive")
        if self.cleaned_total_samples < 0:
            raise ValueError("subtitle cleaned total must be non-negative")
        if self.original_total_samples < self.cleaned_total_samples:
            raise ValueError("subtitle original total must not be shorter than cleaned")
        keys = tuple(key for key, _ in self.configuration_snapshot)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("subtitle configuration snapshot must be sorted and unique")
        if not self.blocks:
            raise ValueError("subtitle document requires at least one block")


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    """Portable processing outcome without user content or absolute paths."""

    schema_version: str
    project_id: str
    status: ProcessingStatus
    pipeline_version: str
    stage: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    component_versions: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.pipeline_version:
            raise ValueError("report versions must not be empty")
        if not self.project_id:
            raise ValueError("project_id must not be empty")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """One portable artifact entry for ``manifest.json``."""

    relative_path: PurePosixPath
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.relative_path.is_absolute() or ".." in self.relative_path.parts:
            raise ValueError("artifact path must be safe and relative")
        if self.size_bytes < 0:
            raise ValueError("artifact size must be non-negative")
        if not self.sha256:
            raise ValueError("artifact sha256 must not be empty")


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    """Versioned portable manifest for the final artifact set."""

    schema_version: str
    project_id: str
    pipeline_version: str
    artifacts: tuple[ArtifactRecord, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.pipeline_version:
            raise ValueError("manifest versions must not be empty")
        if not self.project_id:
            raise ValueError("project_id must not be empty")


@dataclass(frozen=True, slots=True)
class PauseRemovalResult:
    """Boundary result for a future pause-removal adapter."""

    cleaned_audio_path: Path
    edit_map: EditMap
    cleaned_audio: AudioInfo | None = None


@dataclass(frozen=True, slots=True)
class AudioLoadResult:
    """Source and canonical metadata returned by the headless audio loader."""

    source_audio: AudioInfo
    canonical_audio: AudioInfo


def _validate_edit_map_spans(edit_map: EditMap) -> None:
    if edit_map.source_total_samples == 0:
        if edit_map.spans or edit_map.output_total_samples != 0:
            raise ValueError("empty source edit map must have an empty timeline")
        return
    if not edit_map.spans:
        raise ValueError("non-empty source edit map requires timeline spans")

    source_cursor = 0
    target_cursor = 0
    removed_samples = 0
    for span in edit_map.spans:
        if span.source_start != source_cursor:
            raise ValueError("edit spans must partition the source timeline")
        if span.kind is EditKind.KEEP:
            if span.target_start != target_cursor:
                raise ValueError("kept target spans must be continuous")
            target_cursor = span.target_end
        else:
            if span.target_start != target_cursor or span.target_end != target_cursor:
                raise ValueError("removed span must collapse at the target cursor")
            removed_samples += span.removed_samples
        source_cursor = span.source_end

    if source_cursor != edit_map.source_total_samples:
        raise ValueError("edit spans do not cover the source sample count")
    if target_cursor != edit_map.output_total_samples:
        raise ValueError("edit spans do not cover the target sample count")
    if removed_samples != (
        edit_map.source_total_samples - edit_map.output_total_samples
    ):
        raise ValueError("removed sample total does not match timeline durations")
