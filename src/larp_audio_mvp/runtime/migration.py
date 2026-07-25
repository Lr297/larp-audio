"""Conservative migration policy for pre-managed development preferences."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LegacyPreferencesDecision:
    managed_model_selected: bool
    output_directory: Path
    ignored_legacy_model: Path | None
    reset_unsafe_output: bool


def migrate_subtitle_word_limit(value: object) -> tuple[int, bool]:
    """Replace obsolete user word limits with the internal semantic ceiling."""

    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 10, value is not None
    return 10, parsed != 10


def migrate_legacy_preferences(
    *,
    legacy_model: Path | None,
    legacy_output: Path | None,
    managed_model: Path | None,
    default_output: Path,
    application_data: Path,
) -> LegacyPreferencesDecision:
    """Never silently adopt an arbitrary legacy model or unsafe output path."""
    selected_output = default_output
    reset = False
    if legacy_output is not None:
        candidate = legacy_output.resolve(strict=False)
        data = application_data.resolve(strict=False)
        unsafe = candidate == data or data in candidate.parents or candidate in data.parents
        if not unsafe:
            selected_output = candidate
        else:
            reset = True
    return LegacyPreferencesDecision(
        managed_model_selected=managed_model is not None,
        output_directory=selected_output,
        ignored_legacy_model=legacy_model,
        reset_unsafe_output=reset,
    )
