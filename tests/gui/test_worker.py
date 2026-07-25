from __future__ import annotations

from pathlib import Path

from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.errors import SubtitleCoverageError
from larp_audio_mvp.gui.workers import GenerationRequest, SubtitleGenerationWorker
from larp_audio_mvp.subtitles import read_subtitle_document
from larp_audio_mvp.subtitles.service import SubtitleGenerationSummary


class ProjectFailingService:
    def generate(self, **kwargs):
        raise SubtitleCoverageError("coverage", code="TEST_COVERAGE")


class UnexpectedFailingService:
    def generate(self, **kwargs):
        raise RuntimeError("secret details")


class SuccessfulFakeService:
    def generate(self, **kwargs):
        blocks = kwargs["blocks_output"]
        srt = kwargs["srt_output"]
        blocks.write_bytes(Path("examples/stage_9_1_example_subtitle_blocks.json").read_bytes())
        srt.write_bytes(Path("examples/stage_9_1_example_subtitles.srt").read_bytes())
        document = read_subtitle_document(blocks)
        diagnostics = document.diagnostics
        return SubtitleGenerationSummary(
            subtitle_blocks_path=blocks,
            srt_path=srt,
            schema_version=document.schema_version,
            block_count=diagnostics.total_blocks,
            script_word_count=diagnostics.total_script_words,
            exported_word_count=diagnostics.exported_script_words,
            unresolved_word_count=diagnostics.unresolved_script_words,
            interpolated_word_count=diagnostics.interpolated_script_words,
            text_coverage=diagnostics.text_coverage,
            timing_coverage=diagnostics.timing_coverage,
            maximum_characters_per_second=diagnostics.maximum_characters_per_second,
            single_word_blocks=diagnostics.single_word_blocks,
            short_blocks=diagnostics.short_blocks,
            average_words_per_block=diagnostics.average_words_per_block,
            output_paths_validated=True,
            existing_outputs_replaced=False,
            rollback_performed=False,
            warnings_count=diagnostics.warnings_count,
            srt_exportable=True,
        )


def _request(tmp_path: Path) -> GenerationRequest:
    return GenerationRequest(
        alignment_path=tmp_path / "alignment.json",
        output_directory=tmp_path,
        settings=SubtitleSettings(),
    )


def test_worker_project_error_signals_are_safe(qapp, tmp_path: Path) -> None:
    worker = SubtitleGenerationWorker(_request(tmp_path), ProjectFailingService())  # type: ignore[arg-type]
    failures: list[object] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert failures[0].code == "TEST_COVERAGE"
    assert finished == [True]


def test_worker_success_emits_progress_result_and_finished(qapp, tmp_path: Path) -> None:
    worker = SubtitleGenerationWorker(_request(tmp_path), SuccessfulFakeService())  # type: ignore[arg-type]
    started: list[bool] = []
    progress: list[str] = []
    succeeded: list[object] = []
    finished: list[bool] = []
    worker.started.connect(lambda: started.append(True))
    worker.progress.connect(progress.append)
    worker.succeeded.connect(succeeded.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert started == [True]
    assert progress[0] == "Validating alignment"
    assert progress[-1] == "Complete"
    assert succeeded[0].document.schema_version == "subtitle_blocks.schema.v1"
    assert finished == [True]


def test_worker_unexpected_error_is_sanitized(qapp, tmp_path: Path) -> None:
    worker = SubtitleGenerationWorker(_request(tmp_path), UnexpectedFailingService())  # type: ignore[arg-type]
    failures: list[object] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert failures[0].code == "GUI_INTERNAL_ERROR"
    assert "secret" not in failures[0].message
    assert finished == [True]
