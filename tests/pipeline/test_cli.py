from __future__ import annotations

import json
from pathlib import Path

import pytest

from larp_audio_mvp.app import process_audio
from larp_audio_mvp.core.errors import PipelineValidationError
from larp_audio_mvp.pipeline.contracts import PipelineCleanupOutcome, PipelineStage
from larp_audio_mvp.pipeline.failures import PipelineRunFailure

from .test_full_pipeline import make_service, write_wav


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    audio = tmp_path / "audio.wav"; write_wav(audio)
    script = tmp_path / "script.txt"; script.write_text("Hello missing world.\nПривет, мир!", encoding="utf-8", newline="")
    model = tmp_path / "model"; model.mkdir()
    output = tmp_path / "output"; output.mkdir()
    return audio, script, model, output


def test_fake_cli_uses_shared_full_service(monkeypatch, tmp_path: Path, capsys) -> None:
    audio, script, model, output = _inputs(tmp_path)
    monkeypatch.setattr(process_audio, "create_full_processing_service", lambda **kwargs: make_service([]))
    code = process_audio.main(["--audio", str(audio), "--script-file", str(script), "--model-path", str(model), "--model", "tiny", "--output-parent", str(output)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert Path(payload["output_directory"]).is_dir()
    assert Path(payload["package_zip_path"]).is_file()
    assert "recognizing_speech" in captured.err


def test_cli_preflight_failure_is_controlled(tmp_path: Path, capsys) -> None:
    audio, script, model, output = _inputs(tmp_path)
    missing = tmp_path / "missing-ffmpeg"
    code = process_audio.main(["--audio", str(audio), "--script-file", str(script), "--model-path", str(model), "--model", "tiny", "--output-parent", str(output), "--ffmpeg", str(missing), "--ffprobe", str(missing)])
    captured = capsys.readouterr()
    assert code == 2
    assert "TOOL_NOT_FOUND" in captured.err
    assert captured.out == ""


def test_script_stdin_and_file_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        process_audio.main(["--audio", "a", "--script-file", "s", "--script-stdin", "--model-path", "m", "--model", "tiny", "--output-parent", "o"])


def test_cli_failure_reports_primary_and_cleanup_without_traceback(monkeypatch, tmp_path: Path, capsys) -> None:
    audio, script, model, output = _inputs(tmp_path)
    cleanup = PipelineCleanupOutcome(
        True, False, ".run.partial", True,
        error_code="PIPELINE_CLEANUP_FAILED",
        message="cleanup incomplete",
        manual_cleanup_may_be_required=True,
        residual_workspace_path=tmp_path / ".run.partial",
    )
    failure = PipelineRunFailure(
        PipelineValidationError("recognition failed", code="PRIMARY_FAILURE"),
        failed_stage=PipelineStage.RECOGNIZING_SPEECH,
        cleanup_outcome=cleanup,
    )

    class Service:
        def run(self, *args, **kwargs):
            raise failure

    monkeypatch.setattr(process_audio, "create_full_processing_service", lambda **kwargs: Service())
    code = process_audio.main(["--audio", str(audio), "--script-file", str(script), "--model-path", str(model), "--model", "tiny", "--output-parent", str(output)])
    captured = capsys.readouterr()
    assert code == 2 and captured.out == ""
    assert "primary_error_code=PRIMARY_FAILURE" in captured.err
    assert "failed_stage=recognizing_speech" in captured.err
    assert "cleanup_completed=false" in captured.err
    assert "secondary_error_code=PIPELINE_CLEANUP_FAILED" in captured.err
    assert f"residual_workspace_path={tmp_path / '.run.partial'}" in captured.err
    assert "residual_workspace_exists=true" in captured.err
    assert "manual_cleanup_may_be_required=true" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("cleanup", "path_expected"),
    (
        (PipelineCleanupOutcome(True, True, None, False, message="removed"), False),
        (PipelineCleanupOutcome(False, True, None, False, message="no workspace"), False),
        (PipelineCleanupOutcome(False, False, None, False, message="unknown"), False),
    ),
)
def test_cli_does_not_invent_residual_path(capsys, cleanup: PipelineCleanupOutcome, path_expected: bool) -> None:
    failure = PipelineRunFailure(
        PipelineValidationError("failed", code="PRIMARY"),
        failed_stage=PipelineStage.PREFLIGHT,
        cleanup_outcome=cleanup,
    )
    process_audio._print_pipeline_failure(failure)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ("residual_workspace_path=" in captured.err) is path_expected
    assert "primary_error_code=PRIMARY" in captured.err
