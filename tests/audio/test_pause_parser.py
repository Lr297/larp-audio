from __future__ import annotations

from fractions import Fraction

import pytest

from larp_audio_mvp.audio.pause_parser import parse_silencedetect_output
from larp_audio_mvp.core.errors import PauseDetectionError


def test_empty_and_unexpected_stderr_produce_no_pauses() -> None:
    assert _parse("") == []
    assert _parse("localized progress: frame=100\nunknown diagnostic") == []


def test_one_pause_uses_exact_conservative_sample_rounding() -> None:
    segments = _parse(
        "[silencedetect @ 0x1] silence_start: 0.100001\n"
        "[silencedetect @ 0x1] silence_end: 0.2 | silence_duration: 0.099999"
    )

    assert len(segments) == 1
    segment = segments[0]
    assert segment.start_sample == 4_801
    assert segment.end_sample == 9_600
    assert segment.length_samples == 4_799
    assert segment.start_seconds == Fraction(4_801, 48_000)


def test_multiple_pauses_are_sorted_and_non_overlapping() -> None:
    segments = _parse(
        "silence_start: 2\n"
        "silence_end: 3\n"
        "silence_start: 0.5\n"
        "silence_end: 1.5\n"
    )

    assert [(item.start_sample, item.end_sample) for item in segments] == [
        (24_000, 72_000),
        (96_000, 144_000),
    ]


def test_overlaps_touching_intervals_and_duplicates_are_merged() -> None:
    segments = _parse(
        "silence_start: 1\n"
        "silence_end: 3\n"
        "silence_start: 2\n"
        "silence_end: 4\n"
        "silence_start: 4\n"
        "silence_end: 5\n"
        "silence_start: 1\n"
        "silence_end: 3\n"
    )

    assert [(item.start_sample, item.end_sample) for item in segments] == [
        (48_000, 240_000)
    ]


def test_surrounding_localized_text_does_not_affect_machine_keys() -> None:
    segments = _parse(
        "локализованное сообщение silence_start: 1\n"
        "autre message silence_end: 2 | durée: 1"
    )

    assert segments[0].start_sample == 48_000
    assert segments[0].end_sample == 96_000


@pytest.mark.parametrize(
    ("stderr", "code"),
    [
        ("silence_start:", "MALFORMED_SILENCE_EVENT"),
        ("silence_end: incomplete", "MALFORMED_SILENCE_EVENT"),
        ("silence_start: 1", "TRUNCATED_SILENCE_EVENT"),
        ("silence_end: 2", "UNPAIRED_SILENCE_END"),
        (
            "silence_start: 1\nsilence_start: 2\nsilence_end: 3",
            "OVERLAPPING_SILENCE_EVENTS",
        ),
    ],
)
def test_malformed_or_truncated_events_are_rejected(
    stderr: str, code: str
) -> None:
    with pytest.raises(PauseDetectionError) as captured:
        _parse(stderr)

    assert captured.value.code == code


def test_out_of_bounds_interval_is_rejected() -> None:
    with pytest.raises(PauseDetectionError) as captured:
        _parse("silence_start: 5\nsilence_end: 7", total_samples=288_000)

    assert captured.value.code == "PAUSE_OUT_OF_BOUNDS"


def test_interval_shorter_than_required_samples_is_filtered() -> None:
    assert _parse(
        "silence_start: 1\nsilence_end: 1.1",
        minimum_pause_samples=4_801,
    ) == []


def _parse(
    stderr: str,
    *,
    total_samples: int = 288_000,
    minimum_pause_samples: int = 1,
):
    return parse_silencedetect_output(
        stderr,
        sample_rate=48_000,
        total_samples=total_samples,
        minimum_pause_samples=minimum_pause_samples,
    )
