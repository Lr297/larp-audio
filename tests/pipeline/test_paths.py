from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import PipelineWorkspaceError
from larp_audio_mvp.pipeline.paths import PipelinePathPlan, sanitize_run_stem


def test_run_name_is_cross_platform_safe_and_collision_suffixed(tmp_path: Path) -> None:
    source = tmp_path / 'veľmi:dlhý? názov<>.wav'
    source.write_bytes(b'audio')
    model = tmp_path / 'model'; model.mkdir()
    parent = tmp_path / 'output'; parent.mkdir()
    first = PipelinePathPlan.build(source_audio=source, script_source=None, model_path=model, output_parent=parent, name_suffix='20260101_010203', run_id='fixed')
    assert not any(character in first.run_name for character in '<>:"/\\|?*')
    first.final_directory.mkdir()
    second = PipelinePathPlan.build(source_audio=source, script_source=None, model_path=model, output_parent=parent, name_suffix='20260101_010203', run_id='fixed')
    assert second.run_name.endswith('_2')


def test_staging_publication_is_atomic_and_cleanup_is_scoped(tmp_path: Path) -> None:
    source = tmp_path / 'audio.wav'; source.write_bytes(b'audio')
    model = tmp_path / 'model'; model.mkdir()
    parent = tmp_path / 'output'; parent.mkdir()
    plan = PipelinePathPlan.build(source_audio=source, script_source=None, model_path=model, output_parent=parent, name_suffix='fixed', run_id='run')
    plan.create_staging()
    (plan.staging_directory / 'artifact').write_text('ok')
    plan.publish()
    assert (plan.final_directory / 'artifact').read_text() == 'ok'
    assert not plan.staging_directory.exists()


def test_invalid_parent_and_symlink_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / 'audio.wav'; source.write_bytes(b'audio')
    model = tmp_path / 'model'; model.mkdir()
    parent_file = tmp_path / 'file'; parent_file.write_text('x')
    with pytest.raises(PipelineWorkspaceError):
        PipelinePathPlan.build(source_audio=source, script_source=None, model_path=model, output_parent=parent_file, name_suffix='x', run_id='x')
    if hasattr(Path, 'symlink_to'):
        real = tmp_path / 'real'; real.mkdir()
        link = tmp_path / 'link'; link.symlink_to(real, target_is_directory=True)
        with pytest.raises(PipelineWorkspaceError):
            PipelinePathPlan.build(source_audio=source, script_source=None, model_path=model, output_parent=link, name_suffix='x', run_id='x')


def test_long_or_empty_stems_are_bounded() -> None:
    assert len(sanitize_run_stem('ü' * 500)) <= 64
    assert sanitize_run_stem(' ... ') == 'audio'
