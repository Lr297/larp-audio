"""Typed, explicit TOML configuration with no environment-variable loading."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from larp_audio_mvp.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class PathSettings:
    workspace_root: Path
    output_root: Path
    model_root: Path
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    bundled_tools_directory: Path | None = None

    def __post_init__(self) -> None:
        for name in ("workspace_root", "output_root", "model_root"):
            value = getattr(self, name)
            if not value.is_absolute():
                raise ConfigurationError(f"{name} must resolve to an absolute path")
        for name in ("ffmpeg_path", "ffprobe_path", "bundled_tools_directory"):
            value = getattr(self, name)
            if value is not None and not value.is_absolute():
                raise ConfigurationError(f"{name} must resolve to an absolute path")

    @property
    def work_directory(self) -> Path:
        """Explicit alias used by the audio-ingestion stage."""

        return self.workspace_root


@dataclass(frozen=True, slots=True)
class AudioSettings:
    """Validated process and canonical-audio policy for MVP ingestion."""

    subprocess_timeout_seconds: float = 60.0
    canonical_container: str = "wav"
    canonical_codec: str = "pcm_s16le"
    canonical_sample_format: str = "s16"
    canonical_sample_rate: int = 48_000
    canonical_channels: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.subprocess_timeout_seconds, bool) or not isinstance(
            self.subprocess_timeout_seconds, (int, float)
        ):
            raise ConfigurationError(
                "subprocess_timeout_seconds must be a positive finite number"
            )
        if (
            not isfinite(self.subprocess_timeout_seconds)
            or self.subprocess_timeout_seconds <= 0
        ):
            raise ConfigurationError(
                "subprocess_timeout_seconds must be a positive finite number"
            )
        for name in ("canonical_sample_rate", "canonical_channels"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigurationError(f"{name} must be an integer")
        expected = {
            "canonical_container": (self.canonical_container, "wav"),
            "canonical_codec": (self.canonical_codec, "pcm_s16le"),
            "canonical_sample_format": (self.canonical_sample_format, "s16"),
            "canonical_sample_rate": (self.canonical_sample_rate, 48_000),
            "canonical_channels": (self.canonical_channels, 1),
        }
        for name, (actual, supported) in expected.items():
            if actual != supported:
                raise ConfigurationError(
                    f"unsupported {name}: {actual!r}; MVP requires {supported!r}"
                )


@dataclass(frozen=True, slots=True)
class PauseSettings:
    """Uncalibrated pause policy fields; no hidden numerical defaults."""

    silence_threshold_db: Decimal | None = None
    minimum_pause_duration_ms: int | None = None
    shortening_policy_version: str | None = None
    minimum_pause_to_shorten_ms: int | None = None
    target_remaining_pause_ms: int | None = None
    maximum_removed_per_pause_ms: int | None = None
    long_pause_threshold_ms: int | None = None
    retained_pause_ms: int | None = None
    pre_word_guard_ms: int | None = None
    post_word_guard_ms: int | None = None
    preserve_edge_silence: bool = True

    def __post_init__(self) -> None:
        if self.silence_threshold_db is not None:
            if isinstance(self.silence_threshold_db, bool):
                raise ConfigurationError("silence_threshold_db must be a number")
            try:
                threshold = Decimal(str(self.silence_threshold_db))
            except (InvalidOperation, ValueError) as exc:
                raise ConfigurationError(
                    "silence_threshold_db must be a finite number"
                ) from exc
            if not threshold.is_finite() or not Decimal("-120") <= threshold < 0:
                raise ConfigurationError(
                    "silence_threshold_db must be in the range [-120, 0)"
                )
            object.__setattr__(self, "silence_threshold_db", threshold)

        values = {
            "minimum_pause_duration_ms": self.minimum_pause_duration_ms,
            "minimum_pause_to_shorten_ms": self.minimum_pause_to_shorten_ms,
            "target_remaining_pause_ms": self.target_remaining_pause_ms,
            "maximum_removed_per_pause_ms": self.maximum_removed_per_pause_ms,
            "long_pause_threshold_ms": self.long_pause_threshold_ms,
            "retained_pause_ms": self.retained_pause_ms,
            "pre_word_guard_ms": self.pre_word_guard_ms,
            "post_word_guard_ms": self.post_word_guard_ms,
        }
        for name, value in values.items():
            if isinstance(value, bool) or (
                value is not None and not isinstance(value, int)
            ):
                raise ConfigurationError(f"{name} must be an integer")
            if value is not None and value < 0:
                raise ConfigurationError(f"{name} must be non-negative")
        if (
            self.minimum_pause_duration_ms is not None
            and self.minimum_pause_duration_ms == 0
        ):
            raise ConfigurationError(
                "minimum_pause_duration_ms must be positive"
            )
        shortening_values = (
            self.minimum_pause_to_shorten_ms,
            self.target_remaining_pause_ms,
            self.maximum_removed_per_pause_ms,
        )
        if any(value is not None for value in shortening_values):
            if any(value is None for value in shortening_values):
                raise ConfigurationError(
                    "all pause-shortening duration settings must be provided"
                )
            if self.shortening_policy_version is None:
                raise ConfigurationError(
                    "shortening_policy_version is required for pause shortening"
                )
            if (
                not isinstance(self.shortening_policy_version, str)
                or not self.shortening_policy_version.strip()
            ):
                raise ConfigurationError(
                    "shortening_policy_version must not be blank"
                )
            assert self.minimum_pause_to_shorten_ms is not None
            assert self.target_remaining_pause_ms is not None
            assert self.maximum_removed_per_pause_ms is not None
            if self.target_remaining_pause_ms <= 0:
                raise ConfigurationError(
                    "target_remaining_pause_ms must be positive"
                )
            if self.minimum_pause_to_shorten_ms <= self.target_remaining_pause_ms:
                raise ConfigurationError(
                    "minimum_pause_to_shorten_ms must exceed "
                    "target_remaining_pause_ms"
                )
            if self.maximum_removed_per_pause_ms <= 0:
                raise ConfigurationError(
                    "maximum_removed_per_pause_ms must be positive"
                )
        elif self.shortening_policy_version is not None:
            raise ConfigurationError(
                "shortening durations are required with shortening_policy_version"
            )
        if not isinstance(self.preserve_edge_silence, bool):
            raise ConfigurationError("preserve_edge_silence must be a boolean")
        if (
            self.long_pause_threshold_ms is not None
            and self.retained_pause_ms is not None
            and self.retained_pause_ms > self.long_pause_threshold_ms
        ):
            raise ConfigurationError(
                "retained_pause_ms must not exceed long_pause_threshold_ms"
            )


def desktop_mvp_pause_settings() -> PauseSettings:
    """Return the one documented desktop MVP pause-policy baseline."""

    return PauseSettings(
        silence_threshold_db=Decimal("-50"),
        minimum_pause_duration_ms=300,
        shortening_policy_version="desktop-mvp-v1",
        minimum_pause_to_shorten_ms=500,
        target_remaining_pause_ms=200,
        maximum_removed_per_pause_ms=1_000,
    )


@dataclass(frozen=True, slots=True)
class SubtitleSettings:
    """Bounded deterministic subtitle segmentation and layout policy."""

    max_lines: int = 2
    max_characters_per_line: int = 32
    max_words_per_block: int = 10
    min_duration_ms: int = 800
    max_duration_ms: int = 7_000
    max_characters_per_second: Decimal = Decimal("20")
    preferred_gap_break_ms: int = 450
    strong_gap_break_ms: int = 1_200
    preferred_min_words_per_block: int = 2
    preferred_min_visible_chars: int = 8
    new_block_penalty: int = 1_800
    single_word_block_penalty: int = 1_600
    short_block_penalty: int = 800
    max_unresolved_words_per_block: int = 2
    minimum_timing_coverage_for_export: Decimal = Decimal("0.70")
    allow_unresolved_attachment: bool = True
    max_segmentation_cells: int = 250_000
    _allow_legacy_word_limit: bool = False

    def __post_init__(self) -> None:
        integer_values = {
            "max_lines": self.max_lines,
            "max_characters_per_line": self.max_characters_per_line,
            "max_words_per_block": self.max_words_per_block,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "preferred_gap_break_ms": self.preferred_gap_break_ms,
            "strong_gap_break_ms": self.strong_gap_break_ms,
            "preferred_min_words_per_block": self.preferred_min_words_per_block,
            "preferred_min_visible_chars": self.preferred_min_visible_chars,
            "new_block_penalty": self.new_block_penalty,
            "single_word_block_penalty": self.single_word_block_penalty,
            "short_block_penalty": self.short_block_penalty,
            "max_segmentation_cells": self.max_segmentation_cells,
        }
        for name, value in integer_values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigurationError(f"{name} must be positive")
        if not self._allow_legacy_word_limit and self.max_words_per_block != 10:
            raise ConfigurationError(
                "production semantic phrase safety ceiling is fixed at 10 words"
            )
        if self._allow_legacy_word_limit and self.max_words_per_block > 10:
            raise ConfigurationError("historical max_words_per_block must not exceed 10")
        if self.min_duration_ms > self.max_duration_ms:
            raise ConfigurationError(
                "min_duration_ms must not exceed max_duration_ms"
            )
        if self.strong_gap_break_ms <= self.preferred_gap_break_ms:
            raise ConfigurationError(
                "strong_gap_break_ms must exceed preferred_gap_break_ms"
            )
        if (
            isinstance(self.max_unresolved_words_per_block, bool)
            or not isinstance(self.max_unresolved_words_per_block, int)
            or self.max_unresolved_words_per_block < 0
        ):
            raise ConfigurationError(
                "max_unresolved_words_per_block must be non-negative"
            )
        for name in (
            "max_characters_per_second",
            "minimum_timing_coverage_for_export",
        ):
            raw = getattr(self, name)
            if isinstance(raw, bool):
                raise ConfigurationError(f"{name} must be a number")
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError) as exc:
                raise ConfigurationError(f"{name} must be finite") from exc
            if not value.is_finite() or value <= 0:
                raise ConfigurationError(f"{name} must be positive and finite")
            if name == "minimum_timing_coverage_for_export" and value > 1:
                raise ConfigurationError(f"{name} must be in (0, 1]")
            object.__setattr__(self, name, value)
        if not isinstance(self.allow_unresolved_attachment, bool):
            raise ConfigurationError("allow_unresolved_attachment must be boolean")

    @property
    def preferred_min_duration_ms(self) -> int:
        """Explicit semantic name retained beside the historical config key."""

        return self.min_duration_ms

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                {
                    "allow_unresolved_attachment": str(
                        self.allow_unresolved_attachment
                    ).lower(),
                    "max_characters_per_line": str(
                        self.max_characters_per_line
                    ),
                    "max_characters_per_second": format(
                        self.max_characters_per_second, "f"
                    ),
                    "max_duration_ms": str(self.max_duration_ms),
                    "max_lines": str(self.max_lines),
                    "max_segmentation_cells": str(self.max_segmentation_cells),
                    "max_unresolved_words_per_block": str(
                        self.max_unresolved_words_per_block
                    ),
                    "max_words_per_block": str(self.max_words_per_block),
                    "minimum_timing_coverage_for_export": format(
                        self.minimum_timing_coverage_for_export, "f"
                    ),
                    "new_block_penalty": str(self.new_block_penalty),
                    "policy_version": (
                        "conservative-subtitles-v8-syntax-guardrails-45chars-gapless"
                    ),
                    "preferred_gap_break_ms": str(self.preferred_gap_break_ms),
                    "preferred_min_duration_ms": str(self.min_duration_ms),
                    "preferred_min_visible_chars": str(
                        self.preferred_min_visible_chars
                    ),
                    "preferred_min_words_per_block": str(
                        self.preferred_min_words_per_block
                    ),
                    "short_block_penalty": str(self.short_block_penalty),
                    "single_word_block_penalty": str(
                        self.single_word_block_penalty
                    ),
                    "strong_gap_break_ms": str(self.strong_gap_break_ms),
                }.items()
            )
        )


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Validated local Faster-Whisper inference settings."""

    recognizer_executable: Path | None = None
    model_path: Path | None = None
    whisper_backend: str = "faster-whisper"
    whisper_model: str | None = None
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    beam_size: int = 5
    temperature: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("recognizer_executable", "model_path"):
            value = getattr(self, name)
            if value is not None and not value.is_absolute():
                raise ConfigurationError(f"{name} must resolve to an absolute path")
        if self.language is not None and not self.language.strip():
            raise ConfigurationError("language must not be blank")
        if self.language is not None and any(
            character.isspace() for character in self.language
        ):
            raise ConfigurationError("language must not contain whitespace")
        if self.whisper_backend != "faster-whisper":
            raise ConfigurationError(
                "whisper_backend must be 'faster-whisper' for MVP"
            )
        if self.whisper_model not in (None, "tiny", "base", "small"):
            raise ConfigurationError(
                "whisper_model must be one of: tiny, base, small"
            )
        if self.device not in ("cpu", "cuda", "auto"):
            raise ConfigurationError("device must be one of: cpu, cuda, auto")
        supported_compute_types = {
            "auto",
            "default",
            "int8",
            "int8_float16",
            "int8_float32",
            "int8_bfloat16",
            "int16",
            "float16",
            "bfloat16",
            "float32",
        }
        if self.compute_type not in supported_compute_types:
            raise ConfigurationError(
                "compute_type is not supported by the MVP Faster-Whisper adapter"
            )
        if isinstance(self.beam_size, bool) or not isinstance(self.beam_size, int):
            raise ConfigurationError("beam_size must be an integer")
        if not 1 <= self.beam_size <= 100:
            raise ConfigurationError("beam_size must be in the range [1, 100]")
        if isinstance(self.temperature, bool):
            raise ConfigurationError("temperature must be a finite number")
        try:
            temperature = Decimal(str(self.temperature))
        except (InvalidOperation, ValueError) as exc:
            raise ConfigurationError("temperature must be a finite number") from exc
        if not temperature.is_finite() or not Decimal("0") <= temperature <= 1:
            raise ConfigurationError("temperature must be in the range [0, 1]")
        object.__setattr__(self, "temperature", temperature)


@dataclass(frozen=True, slots=True)
class AlignmentSettings:
    """Bounded deterministic script-to-ASR alignment policy."""

    fuzzy_threshold: Decimal = Decimal("0.84")
    min_fuzzy_token_length: int = 4
    max_dp_cells: int = 250_000
    max_interpolation_words: int = 3
    max_interpolation_gap_ms: int = 2_000
    minimum_coverage_warning: Decimal = Decimal("0.80")
    enable_split_merge: bool = True
    enable_fuzzy_matching: bool = True

    def __post_init__(self) -> None:
        for name in ("fuzzy_threshold", "minimum_coverage_warning"):
            value = getattr(self, name)
            if isinstance(value, bool):
                raise ConfigurationError(f"alignment {name} must be a number")
            try:
                decimal = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise ConfigurationError(
                    f"alignment {name} must be a finite number"
                ) from exc
            if not decimal.is_finite() or not Decimal("0") <= decimal <= 1:
                raise ConfigurationError(f"alignment {name} must be in [0, 1]")
            if name == "fuzzy_threshold" and decimal == 0:
                raise ConfigurationError(
                    "alignment fuzzy_threshold must be greater than zero"
                )
            object.__setattr__(self, name, decimal)

        integer_values = {
            "min_fuzzy_token_length": self.min_fuzzy_token_length,
            "max_dp_cells": self.max_dp_cells,
            "max_interpolation_words": self.max_interpolation_words,
            "max_interpolation_gap_ms": self.max_interpolation_gap_ms,
        }
        for name, value in integer_values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigurationError(f"alignment {name} must be an integer")
        if self.min_fuzzy_token_length < 2:
            raise ConfigurationError(
                "alignment min_fuzzy_token_length must be at least 2"
            )
        if self.max_dp_cells < 4:
            raise ConfigurationError("alignment max_dp_cells must be at least 4")
        if self.max_interpolation_words < 0:
            raise ConfigurationError(
                "alignment max_interpolation_words must be non-negative"
            )
        if self.max_interpolation_gap_ms <= 0:
            raise ConfigurationError(
                "alignment max_interpolation_gap_ms must be positive"
            )
        for name in ("enable_split_merge", "enable_fuzzy_matching"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigurationError(f"alignment {name} must be boolean")

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                {
                    "enable_fuzzy_matching": str(
                        self.enable_fuzzy_matching
                    ).lower(),
                    "enable_split_merge": str(self.enable_split_merge).lower(),
                    "fuzzy_threshold": format(self.fuzzy_threshold, "f"),
                    "max_dp_cells": str(self.max_dp_cells),
                    "max_interpolation_gap_ms": str(
                        self.max_interpolation_gap_ms
                    ),
                    "max_interpolation_words": str(
                        self.max_interpolation_words
                    ),
                    "min_fuzzy_token_length": str(
                        self.min_fuzzy_token_length
                    ),
                    "minimum_coverage_warning": format(
                        self.minimum_coverage_warning, "f"
                    ),
                    "policy_version": "script-asr-dp-v1",
                }.items()
            )
        )


@dataclass(frozen=True, slots=True)
class PipelineSettings:
    """Bounded full-workflow limits shared by GUI and CLI."""

    max_script_characters: int = 500_000

    def __post_init__(self) -> None:
        if isinstance(self.max_script_characters, bool) or not isinstance(self.max_script_characters, int) or not 1_000 <= self.max_script_characters <= 10_000_000:
            raise ConfigurationError("pipeline max_script_characters must be in [1000, 10000000]")


@dataclass(frozen=True, slots=True)
class AppConfig:
    paths: PathSettings
    audio: AudioSettings = field(default_factory=AudioSettings)
    pauses: PauseSettings = field(default_factory=PauseSettings)
    subtitles: SubtitleSettings = field(default_factory=SubtitleSettings)
    models: ModelSettings = field(default_factory=ModelSettings)
    alignment: AlignmentSettings = field(default_factory=AlignmentSettings)
    pipeline: PipelineSettings = field(default_factory=PipelineSettings)
    schema_version: int = 1
    source_file: Path | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ConfigurationError(
                f"unsupported configuration schema_version: {self.schema_version}"
            )
        if self.source_file is not None and not self.source_file.is_absolute():
            raise ConfigurationError("source_file must resolve to an absolute path")


def load_config(path: Path) -> AppConfig:
    """Load one explicit TOML file; no `.env` or ambient config is consulted."""

    source_file = path.expanduser().resolve()
    try:
        with source_file.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(
            f"cannot load configuration file: {source_file.name}"
        ) from exc

    base_directory = source_file.parent
    paths = _section(raw, "paths", required=True)
    audio = _section(raw, "audio")
    pauses = _section(raw, "pauses")
    subtitles = _section(raw, "subtitles")
    models = _section(raw, "models")
    alignment = _section(raw, "alignment")
    pipeline = _section(raw, "pipeline")

    schema_version = _integer(raw, "schema_version", default=1)
    return AppConfig(
        schema_version=schema_version,
        source_file=source_file,
        paths=PathSettings(
            workspace_root=_required_path_alias(
                paths, ("work_directory", "workspace_root"), base_directory
            ),
            output_root=_required_path(paths, "output_root", base_directory),
            model_root=_required_path(paths, "model_root", base_directory),
            ffmpeg_path=_optional_path(paths, "ffmpeg_path", base_directory),
            ffprobe_path=_optional_path(paths, "ffprobe_path", base_directory),
            bundled_tools_directory=_optional_path(
                paths, "bundled_tools_directory", base_directory
            ),
        ),
        pipeline=PipelineSettings(
            max_script_characters=_integer(pipeline, "max_script_characters", default=500_000)
        ),
        audio=AudioSettings(
            subprocess_timeout_seconds=_number(
                audio, "subprocess_timeout_seconds", default=60.0
            ),
            canonical_container=_string(
                audio, "canonical_container", default="wav"
            ),
            canonical_codec=_string(
                audio, "canonical_codec", default="pcm_s16le"
            ),
            canonical_sample_format=_string(
                audio, "canonical_sample_format", default="s16"
            ),
            canonical_sample_rate=_integer(
                audio, "canonical_sample_rate", default=48_000
            ),
            canonical_channels=_integer(
                audio, "canonical_channels", default=1
            ),
        ),
        pauses=PauseSettings(
            silence_threshold_db=_optional_decimal(
                pauses, "silence_threshold_db"
            ),
            minimum_pause_duration_ms=_optional_integer(
                pauses, "minimum_pause_duration_ms"
            ),
            shortening_policy_version=_optional_string(
                pauses, "shortening_policy_version"
            ),
            minimum_pause_to_shorten_ms=_optional_integer(
                pauses, "minimum_pause_to_shorten_ms"
            ),
            target_remaining_pause_ms=_optional_integer(
                pauses, "target_remaining_pause_ms"
            ),
            maximum_removed_per_pause_ms=_optional_integer(
                pauses, "maximum_removed_per_pause_ms"
            ),
            long_pause_threshold_ms=_optional_integer(
                pauses, "long_pause_threshold_ms"
            ),
            retained_pause_ms=_optional_integer(pauses, "retained_pause_ms"),
            pre_word_guard_ms=_optional_integer(pauses, "pre_word_guard_ms"),
            post_word_guard_ms=_optional_integer(pauses, "post_word_guard_ms"),
            preserve_edge_silence=_boolean(
                pauses, "preserve_edge_silence", default=True
            ),
        ),
        subtitles=SubtitleSettings(
            max_lines=_integer(subtitles, "max_lines", default=2),
            max_characters_per_line=_integer(
                subtitles, "max_characters_per_line", default=32
            ),
            # The semantic production policy owns its internal safety ceiling;
            # legacy user values no longer control subtitle phrase length.
            max_words_per_block=10,
            min_duration_ms=_integer(
                subtitles, "min_duration_ms", default=800
            ),
            max_duration_ms=_integer(
                subtitles, "max_duration_ms", default=7_000
            ),
            max_characters_per_second=_decimal(
                subtitles,
                "max_characters_per_second",
                default=Decimal("20"),
            ),
            preferred_gap_break_ms=_integer(
                subtitles, "preferred_gap_break_ms", default=450
            ),
            strong_gap_break_ms=_integer(
                subtitles, "strong_gap_break_ms", default=1_200
            ),
            preferred_min_words_per_block=_integer(
                subtitles, "preferred_min_words_per_block", default=2
            ),
            preferred_min_visible_chars=_integer(
                subtitles, "preferred_min_visible_chars", default=8
            ),
            new_block_penalty=_integer(
                subtitles, "new_block_penalty", default=1_800
            ),
            single_word_block_penalty=_integer(
                subtitles, "single_word_block_penalty", default=1_600
            ),
            short_block_penalty=_integer(
                subtitles, "short_block_penalty", default=800
            ),
            max_unresolved_words_per_block=_integer(
                subtitles, "max_unresolved_words_per_block", default=2
            ),
            minimum_timing_coverage_for_export=_decimal(
                subtitles,
                "minimum_timing_coverage_for_export",
                default=Decimal("0.70"),
            ),
            allow_unresolved_attachment=_boolean(
                subtitles, "allow_unresolved_attachment", default=True
            ),
            max_segmentation_cells=_integer(
                subtitles, "max_segmentation_cells", default=250_000
            ),
        ),
        models=ModelSettings(
            recognizer_executable=_optional_path(
                models, "recognizer_executable", base_directory
            ),
            model_path=_optional_path(models, "model_path", base_directory),
            whisper_backend=_string(
                models, "whisper_backend", default="faster-whisper"
            ),
            whisper_model=_optional_string(models, "whisper_model"),
            device=_string(models, "device", default="cpu"),
            compute_type=_string(models, "compute_type", default="int8"),
            language=_optional_string(models, "language"),
            beam_size=_integer(models, "beam_size", default=5),
            temperature=_decimal(models, "temperature", default=Decimal("0")),
        ),
        alignment=AlignmentSettings(
            fuzzy_threshold=_decimal(
                alignment, "fuzzy_threshold", default=Decimal("0.84")
            ),
            min_fuzzy_token_length=_integer(
                alignment, "min_fuzzy_token_length", default=4
            ),
            max_dp_cells=_integer(
                alignment, "max_dp_cells", default=250_000
            ),
            max_interpolation_words=_integer(
                alignment, "max_interpolation_words", default=3
            ),
            max_interpolation_gap_ms=_integer(
                alignment, "max_interpolation_gap_ms", default=2_000
            ),
            minimum_coverage_warning=_decimal(
                alignment,
                "minimum_coverage_warning",
                default=Decimal("0.80"),
            ),
            enable_split_merge=_boolean(
                alignment, "enable_split_merge", default=True
            ),
            enable_fuzzy_matching=_boolean(
                alignment, "enable_fuzzy_matching", default=True
            ),
        ),
    )


def _section(
    data: Mapping[str, Any], name: str, *, required: bool = False
) -> Mapping[str, Any]:
    value = data.get(name)
    if value is None:
        if required:
            raise ConfigurationError(f"missing [{name}] configuration section")
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"[{name}] must be a TOML table")
    return value


def _required_path(data: Mapping[str, Any], key: str, base: Path) -> Path:
    value = _optional_string(data, key)
    if value is None:
        raise ConfigurationError(f"missing required path: {key}")
    return _resolve_path(value, base)


def _required_path_alias(
    data: Mapping[str, Any], keys: tuple[str, ...], base: Path
) -> Path:
    present = [key for key in keys if key in data]
    if not present:
        joined = " or ".join(keys)
        raise ConfigurationError(f"missing required path: {joined}")
    if len(present) > 1:
        raise ConfigurationError(
            f"configure only one path alias, not both: {', '.join(present)}"
        )
    return _required_path(data, present[0], base)


def _optional_path(data: Mapping[str, Any], key: str, base: Path) -> Path | None:
    value = _optional_string(data, key)
    return None if value is None else _resolve_path(value, base)


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value


def _string(data: Mapping[str, Any], key: str, *, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value


def _integer(data: Mapping[str, Any], key: str, *, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{key} must be an integer")
    return value


def _optional_integer(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{key} must be an integer")
    return value


def _optional_number(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{key} must be a number")
    return float(value)


def _optional_decimal(data: Mapping[str, Any], key: str) -> Decimal | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{key} must be a number")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigurationError(f"{key} must be a finite number") from exc
    if not decimal.is_finite():
        raise ConfigurationError(f"{key} must be a finite number")
    return decimal


def _decimal(
    data: Mapping[str, Any], key: str, *, default: Decimal
) -> Decimal:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ConfigurationError(f"{key} must be a number")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigurationError(f"{key} must be a finite number") from exc
    if not decimal.is_finite():
        raise ConfigurationError(f"{key} must be a finite number")
    return decimal


def _number(data: Mapping[str, Any], key: str, *, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{key} must be a number")
    return float(value)


def _boolean(data: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a boolean")
    return value
