from __future__ import annotations

from pathlib import Path

import pytest

from larp_audio_mvp.core.errors import PipelineCancellationError
from larp_audio_mvp.pipeline import CancellationToken
from larp_audio_mvp.pipeline.contracts import PipelineStage

from .test_full_pipeline import make_request, make_service


@pytest.mark.parametrize(
    "cancel_stage",
    (
        PipelineStage.PREFLIGHT,
        PipelineStage.CANONICALIZING_AUDIO,
        PipelineStage.DETECTING_PAUSES,
        PipelineStage.RECOGNIZING_SPEECH,
        PipelineStage.ALIGNING_SCRIPT,
        PipelineStage.CREATING_PACKAGE,
    ),
)
def test_cancellation_at_safe_boundaries_cleans_and_allows_retry(
    tmp_path: Path, cancel_stage: PipelineStage
) -> None:
    request = make_request(tmp_path)
    source_bytes = request.source_audio_path.read_bytes()
    token = CancellationToken()

    def progress(item) -> None:
        if item.stage is cancel_stage:
            token.request()

    with pytest.raises(PipelineCancellationError):
        make_service([]).run(request, progress=progress, cancellation=token)
    assert request.source_audio_path.read_bytes() == source_bytes
    assert not any(request.output_parent_directory.iterdir())
    assert make_service([]).run(request).completed_successfully


def test_cancellation_is_rejected_after_publication_guard() -> None:
    token = CancellationToken()
    token.prevent_cancellation()
    assert not token.request()
    assert not token.requested
