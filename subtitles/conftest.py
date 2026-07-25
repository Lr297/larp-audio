from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from larp_audio_mvp.alignment import ScriptAlignmentService, read_script
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import (
    AlignmentResult,
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
    ScriptTokenKind,
)


@pytest.fixture
def alignment_factory(tmp_path: Path) -> Callable[..., AlignmentResult]:
    counter = 0

    def make(
        text: str,
        *,
        missing_indices: tuple[int, ...] = (),
        bom: bool = False,
        word_starts: tuple[int, ...] | None = None,
        word_duration: int = 500,
        max_interpolation_gap_ms: int = 2_000,
        sample_rate: int = 1_000,
    ) -> AlignmentResult:
        nonlocal counter
        counter += 1
        path = tmp_path / f"script-{counter}.txt"
        prefix = b"\xef\xbb\xbf" if bom else b""
        path.write_bytes(prefix + text.encode("utf-8"))
        document = read_script(path)
        tokens = tokenize_script(text)
        words = tuple(token for token in tokens if token.kind is ScriptTokenKind.WORD)
        starts = word_starts or tuple(500 + index * 1_000 for index in range(len(words)))
        assert len(starts) == len(words)
        total = max((start + word_duration for start in starts), default=sample_rate) + sample_rate
        edit_map = EditMap(
            schema_version="1",
            policy_version="subtitle-test-v1",
            sample_rate=sample_rate,
            source_total_samples=total,
            output_total_samples=total,
            source_sha256="source-hash",
            output_sha256="cleaned-hash",
            spans=(
                EditSpan(
                    EditKind.KEEP,
                    SampleRange(0, total),
                    SampleRange(0, total),
                    reason="identity",
                ),
            ),
        )
        recognized = tuple(
            RecognizedWord(
                text=token.exact_text,
                sample_rate=sample_rate,
                start_sample_cleaned=starts[index],
                end_sample_cleaned=starts[index] + word_duration,
                start_sample_original=starts[index],
                end_sample_original=starts[index] + word_duration,
                confidence=0.9,
            )
            for index, token in enumerate(words)
            if index not in missing_indices
        )
        recognition = RecognitionResult(
            schema_version="1",
            backend="faster-whisper",
            model="tiny",
            language=None,
            sample_rate=sample_rate,
            duration_samples_cleaned=total,
            duration_samples_original=total,
            words=recognized,
            metadata=(("cleaned_audio_sha256", "cleaned-hash"),),
        )
        return ScriptAlignmentService(
            AlignmentSettings(max_interpolation_gap_ms=max_interpolation_gap_ms)
        ).align(document, recognition, edit_map)

    return make
