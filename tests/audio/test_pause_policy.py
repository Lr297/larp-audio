from __future__ import annotations

from larp_audio_mvp.audio.pause_policy import PauseShorteningPolicy
from larp_audio_mvp.config import PauseSettings
from larp_audio_mvp.core.contracts import PauseSegment


def _policy(*, maximum_ms: int = 5_000) -> PauseShorteningPolicy:
    return PauseShorteningPolicy(
        PauseSettings(
            shortening_policy_version="test-v1",
            minimum_pause_to_shorten_ms=1_000,
            target_remaining_pause_ms=400,
            maximum_removed_per_pause_ms=maximum_ms,
        )
    )


def test_policy_leaves_short_threshold_and_edge_pauses_unchanged() -> None:
    pauses = [
        PauseSegment(0, 2_000, 1_000),
        PauseSegment(3_000, 4_000, 1_000),
        PauseSegment(8_000, 10_000, 1_000),
    ]

    decisions = _policy().decide(
        pauses, total_samples=10_000, sample_rate=1_000
    )

    assert [decision.shortened for decision in decisions] == [False, False, False]
    assert decisions[0].reason == "preserve_edge_silence"
    assert decisions[1].reason == "below_or_equal_shortening_threshold"
    assert decisions[2].reason == "preserve_edge_silence"


def test_policy_removes_only_center_and_retains_target_pause() -> None:
    pause = PauseSegment(2_000, 4_000, 1_000)

    decision = _policy().decide(
        [pause], total_samples=6_000, sample_rate=1_000
    )[0]

    assert decision.remove_range is not None
    assert (decision.remove_range.start, decision.remove_range.end) == (2_200, 3_800)
    assert decision.retained_before_samples == 200
    assert decision.retained_after_samples == 200
    assert decision.remove_range.end - decision.remove_range.start == 1_600


def test_policy_caps_removed_samples_and_never_removes_entire_pause() -> None:
    pause = PauseSegment(2_000, 4_000, 1_000)

    decision = _policy(maximum_ms=300).decide(
        [pause], total_samples=6_000, sample_rate=1_000
    )[0]

    assert decision.remove_range is not None
    assert decision.remove_range.end - decision.remove_range.start == 300
    assert decision.retained_before_samples == 850
    assert decision.retained_after_samples == 850


def test_policy_sorts_input_deterministically() -> None:
    decisions = _policy().decide(
        [
            PauseSegment(6_000, 8_000, 1_000),
            PauseSegment(2_000, 4_000, 1_000),
        ],
        total_samples=10_000,
        sample_rate=1_000,
    )

    assert [decision.pause.start_sample for decision in decisions] == [2_000, 6_000]
