from __future__ import annotations

from decimal import Decimal

import pytest

from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.errors import ConfigurationError


def test_alignment_configuration_snapshot_is_stable_and_complete() -> None:
    settings = AlignmentSettings()
    snapshot = dict(settings.snapshot())
    assert snapshot["fuzzy_threshold"] == "0.84"
    assert snapshot["max_dp_cells"] == "250000"
    assert snapshot["policy_version"] == "script-asr-dp-v1"
    assert tuple(key for key, _ in settings.snapshot()) == tuple(sorted(snapshot))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fuzzy_threshold": Decimal("0")},
        {"fuzzy_threshold": Decimal("1.1")},
        {"min_fuzzy_token_length": 1},
        {"max_dp_cells": 3},
        {"max_interpolation_words": -1},
        {"max_interpolation_gap_ms": 0},
        {"minimum_coverage_warning": Decimal("-0.1")},
        {"enable_fuzzy_matching": 1},
    ],
)
def test_alignment_configuration_rejects_invalid_values(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ConfigurationError):
        AlignmentSettings(**kwargs)  # type: ignore[arg-type]
