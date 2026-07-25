"""Deterministic policy for shortening only the middle of eligible pauses."""

from __future__ import annotations

from typing import Sequence

from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import (
    PauseSegment,
    PauseShorteningDecision,
    SampleRange,
)
from larp_audio_mvp.core.errors import EditMapError


class PauseShorteningPolicy:
    """Convert normalized pause observations into immutable cut decisions."""

    def __init__(self, settings: PauseSettings) -> None:
        required = (
            settings.shortening_policy_version,
            settings.minimum_pause_to_shorten_ms,
            settings.target_remaining_pause_ms,
            settings.maximum_removed_per_pause_ms,
        )
        if any(value is None for value in required):
            raise EditMapError(
                "pause-shortening policy settings are incomplete",
                code="SHORTENING_POLICY_INCOMPLETE",
            )
        if not settings.preserve_edge_silence:
            raise EditMapError(
                "Stage 6 requires preserve_edge_silence=true",
                code="EDGE_SILENCE_POLICY_UNSUPPORTED",
            )
        self._settings = settings

    @property
    def version(self) -> str:
        assert self._settings.shortening_policy_version is not None
        return self._settings.shortening_policy_version

    def snapshot(self, sample_rate: int) -> tuple[tuple[str, int], ...]:
        minimum, target, maximum = self._sample_limits(sample_rate)
        assert self._settings.minimum_pause_to_shorten_ms is not None
        assert self._settings.target_remaining_pause_ms is not None
        assert self._settings.maximum_removed_per_pause_ms is not None
        return (
            (
                "minimum_pause_to_shorten_ms",
                self._settings.minimum_pause_to_shorten_ms,
            ),
            ("target_remaining_pause_ms", self._settings.target_remaining_pause_ms),
            (
                "maximum_removed_per_pause_ms",
                self._settings.maximum_removed_per_pause_ms,
            ),
            ("minimum_pause_to_shorten_samples", minimum),
            ("target_remaining_pause_samples", target),
            ("maximum_removed_per_pause_samples", maximum),
            ("preserve_edge_silence", 1),
        )

    def decide(
        self,
        pauses: Sequence[PauseSegment],
        *,
        total_samples: int,
        sample_rate: int,
    ) -> tuple[PauseShorteningDecision, ...]:
        if total_samples <= 0 or sample_rate <= 0:
            raise EditMapError(
                "audio sample totals must be positive",
                code="INVALID_AUDIO_TIMELINE",
            )
        ordered = sorted(pauses, key=lambda item: (item.start_sample, item.end_sample))
        _validate_pauses(ordered, total_samples, sample_rate)
        minimum, target, maximum = self._sample_limits(sample_rate)
        decisions: list[PauseShorteningDecision] = []

        for pause in ordered:
            if pause.start_sample == 0 or pause.end_sample == total_samples:
                decisions.append(
                    PauseShorteningDecision(
                        pause=pause,
                        remove_range=None,
                        reason="preserve_edge_silence",
                    )
                )
                continue
            if pause.length_samples <= minimum:
                decisions.append(
                    PauseShorteningDecision(
                        pause=pause,
                        remove_range=None,
                        reason="below_or_equal_shortening_threshold",
                    )
                )
                continue

            removable_above_target = pause.length_samples - target
            removed_samples = min(removable_above_target, maximum)
            if removed_samples <= 0:
                decisions.append(
                    PauseShorteningDecision(
                        pause=pause,
                        remove_range=None,
                        reason="target_already_satisfied",
                    )
                )
                continue

            remaining_samples = pause.length_samples - removed_samples
            retained_before = remaining_samples // 2
            retained_after = remaining_samples - retained_before
            if retained_before <= 0 or retained_after <= 0:
                raise EditMapError(
                    "shortening policy would remove a pause boundary",
                    code="UNSAFE_PAUSE_POLICY",
                )
            remove_range = SampleRange(
                pause.start_sample + retained_before,
                pause.end_sample - retained_after,
            )
            decisions.append(
                PauseShorteningDecision(
                    pause=pause,
                    remove_range=remove_range,
                    reason="shorten_pause_middle",
                    retained_before_samples=retained_before,
                    retained_after_samples=retained_after,
                )
            )
        return tuple(decisions)

    def _sample_limits(self, sample_rate: int) -> tuple[int, int, int]:
        assert self._settings.minimum_pause_to_shorten_ms is not None
        assert self._settings.target_remaining_pause_ms is not None
        assert self._settings.maximum_removed_per_pause_ms is not None
        return (
            _milliseconds_to_samples_ceil(
                self._settings.minimum_pause_to_shorten_ms, sample_rate
            ),
            _milliseconds_to_samples_ceil(
                self._settings.target_remaining_pause_ms, sample_rate
            ),
            _milliseconds_to_samples_ceil(
                self._settings.maximum_removed_per_pause_ms, sample_rate
            ),
        )


def _validate_pauses(
    pauses: Sequence[PauseSegment], total_samples: int, sample_rate: int
) -> None:
    previous_end = 0
    for index, pause in enumerate(pauses):
        if pause.sample_rate != sample_rate:
            raise EditMapError(
                "pause sample rate does not match audio",
                code="PAUSE_SAMPLE_RATE_MISMATCH",
            )
        if pause.end_sample > total_samples:
            raise EditMapError(
                "pause exceeds the source timeline",
                code="PAUSE_OUT_OF_BOUNDS",
            )
        if index and pause.start_sample < previous_end:
            raise EditMapError(
                "pause observations overlap",
                code="OVERLAPPING_PAUSES",
            )
        previous_end = pause.end_sample


def _milliseconds_to_samples_ceil(milliseconds: int, sample_rate: int) -> int:
    return (milliseconds * sample_rate + 999) // 1_000
