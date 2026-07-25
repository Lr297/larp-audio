"""Central user-facing pause-style presets mapped to existing backend settings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PauseStylePreset(StrEnum):
    TIGHT = "tight"
    BALANCED = "balanced"
    NATURAL = "natural"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class PausePresetValues:
    silence_threshold_db: Decimal
    minimum_detected_silence_ms: int
    minimum_pause_to_shorten_ms: int
    retained_pause_ms: int
    maximum_removed_per_pause_ms: int


PAUSE_PRESETS = {
    PauseStylePreset.TIGHT: PausePresetValues(Decimal("-50"), 200, 350, 120, 1_500),
    PauseStylePreset.BALANCED: PausePresetValues(Decimal("-50"), 300, 500, 200, 1_000),
    PauseStylePreset.NATURAL: PausePresetValues(Decimal("-55"), 400, 800, 350, 700),
}


def identify_pause_preset(values: PausePresetValues) -> PauseStylePreset:
    for preset, expected in PAUSE_PRESETS.items():
        if values == expected:
            return preset
    return PauseStylePreset.CUSTOM
