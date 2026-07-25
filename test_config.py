"""Smoke tests for explicit TOML configuration."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from larp_audio_mvp.config import (
    AudioSettings,
    ModelSettings,
    PauseSettings,
    load_config,
)
from larp_audio_mvp.core.errors import ConfigurationError


def test_example_configuration_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config.example.toml")

    assert config.schema_version == 1
    assert config.paths.workspace_root.is_absolute()
    assert config.paths.work_directory == config.paths.workspace_root
    assert config.paths.output_root.is_absolute()
    assert config.paths.model_root.is_absolute()
    assert config.pauses.preserve_edge_silence is True
    assert config.pauses.long_pause_threshold_ms is None
    assert config.pauses.silence_threshold_db is None
    assert config.pauses.minimum_pause_duration_ms is None
    assert config.subtitles.max_lines == 2
    assert config.subtitles.max_characters_per_line == 32
    assert config.subtitles.max_words_per_block == 10
    assert config.subtitles.minimum_timing_coverage_for_export == Decimal("0.70")
    assert config.audio.canonical_sample_rate == 48_000
    assert config.audio.canonical_channels == 1
    assert config.audio.canonical_codec == "pcm_s16le"
    assert config.alignment.fuzzy_threshold == Decimal("0.84")
    assert config.alignment.max_dp_cells == 250_000


def test_configuration_resolves_relative_paths_from_its_file(tmp_path: Path) -> None:
    config_path = tmp_path / "settings.toml"
    config_path.write_text(
        """
schema_version = 1

[paths]
workspace_root = "jobs"
output_root = "result"
model_root = "models"
ffmpeg_path = "tools/ffmpeg"
ffprobe_path = "tools/ffprobe"
bundled_tools_directory = "tools/bundled"

[audio]
subprocess_timeout_seconds = 12.5
canonical_container = "wav"
canonical_codec = "pcm_s16le"
canonical_sample_format = "s16"
canonical_sample_rate = 48000
canonical_channels = 1

[pauses]
silence_threshold_db = -42.5
minimum_pause_duration_ms = 450
shortening_policy_version = "test-v1"
minimum_pause_to_shorten_ms = 1000
target_remaining_pause_ms = 300
maximum_removed_per_pause_ms = 2500
long_pause_threshold_ms = 1000
retained_pause_ms = 300
pre_word_guard_ms = 80
post_word_guard_ms = 120

[subtitles]
max_lines = 2
max_characters_per_line = 42
min_duration_ms = 800
max_duration_ms = 7000
max_characters_per_second = 20.0
max_words_per_block = 8
preferred_gap_break_ms = 500
max_unresolved_words_per_block = 1
minimum_timing_coverage_for_export = 0.8
allow_unresolved_attachment = true
max_segmentation_cells = 1234

[models]
whisper_backend = "faster-whisper"
whisper_model = "tiny"
model_path = "models/tiny"
device = "cpu"
compute_type = "int8"
language = "en"
beam_size = 3
temperature = 0.0

[alignment]
fuzzy_threshold = 0.9
min_fuzzy_token_length = 5
max_dp_cells = 12345
max_interpolation_words = 2
max_interpolation_gap_ms = 900
minimum_coverage_warning = 0.75
enable_split_merge = false
enable_fuzzy_matching = true
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.paths.workspace_root == (tmp_path / "jobs").resolve()
    assert config.paths.ffmpeg_path == (tmp_path / "tools/ffmpeg").resolve()
    assert config.paths.ffprobe_path == (tmp_path / "tools/ffprobe").resolve()
    assert config.paths.bundled_tools_directory == (
        tmp_path / "tools/bundled"
    ).resolve()
    assert config.audio.subprocess_timeout_seconds == 12.5
    assert config.pauses.retained_pause_ms == 300
    assert config.pauses.silence_threshold_db == Decimal("-42.5")
    assert config.pauses.minimum_pause_duration_ms == 450
    assert config.pauses.shortening_policy_version == "test-v1"
    assert config.pauses.minimum_pause_to_shorten_ms == 1000
    assert config.pauses.target_remaining_pause_ms == 300
    assert config.pauses.maximum_removed_per_pause_ms == 2500
    assert config.subtitles.max_characters_per_second == Decimal("20.0")
    assert config.subtitles.max_words_per_block == 10
    assert config.subtitles.preferred_gap_break_ms == 500
    assert config.subtitles.max_segmentation_cells == 1_234
    assert config.models.whisper_model == "tiny"
    assert config.models.model_path == (tmp_path / "models/tiny").resolve()
    assert config.models.beam_size == 3
    assert config.models.temperature == Decimal("0.0")
    assert config.alignment.fuzzy_threshold == Decimal("0.9")
    assert config.alignment.min_fuzzy_token_length == 5
    assert config.alignment.max_dp_cells == 12_345
    assert config.alignment.max_interpolation_words == 2
    assert config.alignment.max_interpolation_gap_ms == 900
    assert config.alignment.minimum_coverage_warning == Decimal("0.75")
    assert config.alignment.enable_split_merge is False


def test_invalid_pause_configuration_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(
        """
[paths]
workspace_root = "jobs"
output_root = "result"
model_root = "models"

[pauses]
long_pause_threshold_ms = 100
retained_pause_ms = 200
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_config(config_path)


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("subprocess_timeout_seconds", 0),
        ("subprocess_timeout_seconds", True),
        ("canonical_container", "mp3"),
        ("canonical_codec", "pcm_s24le"),
        ("canonical_sample_format", "s32"),
        ("canonical_sample_rate", 44_100),
        ("canonical_channels", 2),
        ("canonical_channels", True),
    ],
)
def test_audio_configuration_rejects_non_mvp_invariants(
    keyword: str, value: object
) -> None:
    with pytest.raises(ConfigurationError):
        AudioSettings(**{keyword: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("silence_threshold_db", 0),
        ("silence_threshold_db", -121),
        ("silence_threshold_db", True),
        ("silence_threshold_db", Decimal("NaN")),
        ("minimum_pause_duration_ms", 0),
        ("minimum_pause_duration_ms", -1),
        ("minimum_pause_duration_ms", True),
        ("minimum_pause_duration_ms", 1.5),
    ],
)
def test_pause_detection_configuration_rejects_invalid_values(
    keyword: str, value: object
) -> None:
    with pytest.raises(ConfigurationError):
        PauseSettings(**{keyword: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"shortening_policy_version": "v1", "minimum_pause_to_shorten_ms": 1000},
        {
            "shortening_policy_version": "v1",
            "minimum_pause_to_shorten_ms": 300,
            "target_remaining_pause_ms": 300,
            "maximum_removed_per_pause_ms": 100,
        },
        {
            "shortening_policy_version": "v1",
            "minimum_pause_to_shorten_ms": 1000,
            "target_remaining_pause_ms": 0,
            "maximum_removed_per_pause_ms": 100,
        },
        {
            "shortening_policy_version": "v1",
            "minimum_pause_to_shorten_ms": 1000,
            "target_remaining_pause_ms": 300,
            "maximum_removed_per_pause_ms": 0,
        },
        {"shortening_policy_version": "v1"},
    ],
)
def test_pause_shortening_configuration_rejects_invalid_combinations(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ConfigurationError):
        PauseSettings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"whisper_backend": "cloud"},
        {"whisper_model": "large"},
        {"device": "metal"},
        {"compute_type": "unknown"},
        {"beam_size": 0},
        {"beam_size": True},
        {"temperature": -0.1},
        {"temperature": 1.1},
        {"temperature": Decimal("NaN")},
        {"language": "en us"},
    ],
)
def test_model_configuration_rejects_invalid_values(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ConfigurationError):
        ModelSettings(**overrides)  # type: ignore[arg-type]
