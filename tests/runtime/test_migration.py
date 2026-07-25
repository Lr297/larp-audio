from pathlib import Path

from larp_audio_mvp.runtime.migration import migrate_legacy_preferences


def test_migration_ignores_legacy_model_and_preserves_safe_output(tmp_path: Path) -> None:
    decision = migrate_legacy_preferences(
        legacy_model=tmp_path / "old-model",
        legacy_output=tmp_path / "Documents/results",
        managed_model=tmp_path / "data/engine",
        default_output=tmp_path / "Documents/default",
        application_data=tmp_path / "data",
    )
    assert decision.managed_model_selected
    assert decision.ignored_legacy_model == tmp_path / "old-model"
    assert decision.output_directory == (tmp_path / "Documents/results").resolve()


def test_migration_resets_output_overlapping_application_data(tmp_path: Path) -> None:
    default = tmp_path / "Documents/results"
    decision = migrate_legacy_preferences(
        legacy_model=None,
        legacy_output=tmp_path / "data/exports",
        managed_model=None,
        default_output=default,
        application_data=tmp_path / "data",
    )
    assert decision.output_directory == default
    assert decision.reset_unsafe_output
