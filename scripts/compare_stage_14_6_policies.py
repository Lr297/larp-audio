#!/usr/bin/env python3
"""Compare archived v6, regressed cost-first v7, and conservative v8."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns

from larp_audio_mvp.alignment import (
    ScriptAlignmentService,
    read_script,
    write_alignment_atomic,
)
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import AlignmentSettings, SubtitleSettings
from larp_audio_mvp.core.contracts import (
    EditKind,
    EditMap,
    EditSpan,
    RecognitionResult,
    RecognizedWord,
    SampleRange,
    ScriptTokenKind,
    TimingStatus,
)
from larp_audio_mvp.subtitles.chunker import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.display import subtitle_display_text
from larp_audio_mvp.subtitles.policy import (
    SEMANTIC_MAX_VISIBLE_CHARACTERS,
    SEMANTIC_MAX_WORDS,
    crosses_boundary,
    semantic_boundary_signals,
    word_keys,
)
from larp_audio_mvp.subtitles.repair import is_incomplete_boundary


CORPUS = (
    "Full or not, I make it",
    "Here's what keeps me in business",
    "Women point the finger at age, at childbirth, at weak pelvic floors",
    "Ready or not, we have to begin",
    "This is what keeps the system running",
    "Patients blame stress, poor sleep, and weak muscles",
    "The changes happen at work, at home, and during exercise",
    "If this happens, call your doctor",
    "Whether it works or not, we need an answer",
    "The capsules break down in the stomach before anything reaches the bloodstream",
    "The procedure was carried out by trained nurses",
    "She felt even stronger after the treatment",
)


def _alignment(text: str, directory: Path, index: int):
    script_path = directory / f"script-{index}.txt"
    script_path.write_bytes(text.encode("utf-8"))
    document = read_script(script_path)
    word_tokens = tuple(
        token
        for token in tokenize_script(text)
        if token.kind is ScriptTokenKind.WORD
    )
    sample_rate = 48_000
    starts = tuple(index * 8_000 for index in range(len(word_tokens)))
    word_duration = 6_000
    total = (starts[-1] + word_duration + 8_000) if starts else sample_rate
    edit_map = EditMap(
        schema_version="1",
        policy_version="stage-14.6-comparison",
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
            start_sample_cleaned=starts[position],
            end_sample_cleaned=starts[position] + word_duration,
            start_sample_original=starts[position],
            end_sample_original=starts[position] + word_duration,
            confidence=0.99,
        )
        for position, token in enumerate(word_tokens)
    )
    recognition = RecognitionResult(
        schema_version="1",
        backend="comparison",
        model="local",
        language="en",
        sample_rate=sample_rate,
        duration_samples_cleaned=total,
        duration_samples_original=total,
        words=recognized,
        metadata=(("cleaned_audio_sha256", "cleaned-hash"),),
    )
    return ScriptAlignmentService(AlignmentSettings()).align(
        document, recognition, edit_map
    )


def _regressed_cost_first_ranges(alignment) -> tuple[tuple[int, int], ...]:
    """Reproduce v7's cost-first objective using current legal candidates."""

    chunker = DeterministicSubtitleChunker()
    settings = SubtitleSettings()
    keys = word_keys(alignment.aligned_words)
    exact_words = tuple(word.exact_text for word in alignment.aligned_words)
    signals = semantic_boundary_signals(
        alignment.script.exact_text, alignment.aligned_words, keys
    )
    count = len(alignment.aligned_words)
    infinity = 10**18
    costs = [infinity] * (count + 1)
    cue_counts = [count + 1] * (count + 1)
    previous = [-1] * (count + 1)
    costs[0] = 0
    cue_counts[0] = 0
    for start in range(count):
        if costs[start] == infinity:
            continue
        for end in range(start + 1, min(count, start + SEMANTIC_MAX_WORDS) + 1):
            source_start, source_end = chunker._source_span(alignment, start, end)
            if len(
                subtitle_display_text(
                    alignment.script.exact_text[source_start:source_end]
                )
            ) > SEMANTIC_MAX_VISIBLE_CHARACTERS:
                break
            if crosses_boundary(start, end, signals.required):
                continue
            if (
                end < count
                and end in signals.grammar.syntax.forbidden_boundaries
            ):
                continue
            candidate = chunker._candidate(
                alignment,
                start,
                end,
                settings,
                keys=keys,
                exact_words=exact_words,
                signals=signals,
            )
            if candidate is None:
                continue
            choice = (
                costs[start] + candidate.cost,
                cue_counts[start] + 1,
                start,
            )
            current = (costs[end], cue_counts[end], previous[end])
            if choice < current:
                costs[end], cue_counts[end], previous[end] = choice
    ranges: list[tuple[int, int]] = []
    cursor = count
    while cursor:
        start = previous[cursor]
        if start < 0:
            raise RuntimeError("regressed comparison could not cover corpus")
        ranges.append((start, cursor))
        cursor = start
    return tuple(reversed(ranges))


def _texts_from_ranges(alignment, ranges) -> tuple[str, ...]:
    result = []
    for start, end in ranges:
        char_start, char_end = DeterministicSubtitleChunker._source_span(
            alignment, start, end
        )
        result.append(
            subtitle_display_text(
                alignment.script.exact_text[char_start:char_end]
            )
        )
    return tuple(result)


def _stable_texts(stable_source: Path, alignment_path: Path) -> tuple[str, ...]:
    code = """
import json, sys
from pathlib import Path
from larp_audio_mvp.alignment import read_alignment
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.subtitles.chunker import DeterministicSubtitleChunker
a = read_alignment(Path(sys.argv[1]))
d = DeterministicSubtitleChunker().chunk(
    a, settings=SubtitleSettings(), source_alignment_sha256="6" * 64
)
print(json.dumps([b.display_text_plain for b in d.blocks], ensure_ascii=False))
"""
    environment = {**os.environ, "PYTHONPATH": str(stable_source)}
    completed = subprocess.run(
        [sys.executable, "-c", code, str(alignment_path)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return tuple(json.loads(completed.stdout))


def _metrics(alignment, texts: tuple[str, ...]) -> dict[str, int | float]:
    signals = semantic_boundary_signals(
        alignment.script.exact_text,
        alignment.aligned_words,
        word_keys(alignment.aligned_words),
    )
    positions: list[int] = []
    cursor = 0
    for text in texts[:-1]:
        cursor += len(tokenize_script(text))
        # Count word tokens, because display punctuation may be hidden.
        positions.append(
            sum(
                token.kind is ScriptTokenKind.WORD
                for cue in texts[: len(positions) + 1]
                for token in tokenize_script(cue)
            )
        )
    boundaries = frozenset(positions)
    required = signals.required
    protected = signals.grammar.protected
    unnecessary = 0
    for left, right, boundary in zip(texts, texts[1:], positions):
        if (
            boundary not in required
            and len(subtitle_display_text(f"{left} {right}"))
            <= SEMANTIC_MAX_VISIBLE_CHARACTERS
        ):
            unnecessary += 1
    incomplete = sum(
        is_incomplete_boundary(
            word_keys(alignment.aligned_words), boundary, protected
        )
        for boundary in boundaries
    )
    return {
        "cue_count": len(texts),
        "unnecessary_split_count": unnecessary,
        "list_boundary_hits": len(
            boundaries & signals.grammar.list_item
        ),
        "list_boundary_total": len(signals.grammar.list_item),
        "protected_unit_violations": len(boundaries & protected),
        "incomplete_endings": incomplete,
        "orphan_beginnings": incomplete,
        "maximum_characters": max(map(len, texts), default=0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stable-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    results: dict[str, list[dict[str, object]]] = {
        "stable_v6": [],
        "regressed_v7_cost_first": [],
        "corrected_v8": [],
    }
    with tempfile.TemporaryDirectory(prefix="stage14-6-comparison-") as raw:
        temporary = Path(raw)
        for index, text in enumerate(CORPUS):
            alignment = _alignment(text, temporary, index)
            alignment_path = temporary / f"alignment-{index}.json"
            write_alignment_atomic(alignment, alignment_path)
            started = perf_counter_ns()
            stable = _stable_texts(arguments.stable_source, alignment_path)
            stable_ns = perf_counter_ns() - started
            started = perf_counter_ns()
            regressed = _texts_from_ranges(
                alignment, _regressed_cost_first_ranges(alignment)
            )
            regressed_ns = perf_counter_ns() - started
            started = perf_counter_ns()
            corrected_document = DeterministicSubtitleChunker().chunk(
                alignment,
                settings=SubtitleSettings(),
                source_alignment_sha256="6" * 64,
            )
            corrected_ns = perf_counter_ns() - started
            corrected = tuple(
                block.display_text_plain for block in corrected_document.blocks
            )
            for name, texts, elapsed in (
                ("stable_v6", stable, stable_ns),
                ("regressed_v7_cost_first", regressed, regressed_ns),
                ("corrected_v8", corrected, corrected_ns),
            ):
                results[name].append(
                    {
                        "source": text,
                        "cues": texts,
                        "elapsed_milliseconds": round(elapsed / 1_000_000, 3),
                        **_metrics(alignment, texts),
                    }
                )
    summary = {}
    for name, rows in results.items():
        count = len(rows)
        summary[name] = {
            "average_cues_per_sentence": round(
                sum(int(row["cue_count"]) for row in rows) / count, 3
            ),
            "unnecessary_split_count": sum(
                int(row["unnecessary_split_count"]) for row in rows
            ),
            "list_boundary_accuracy": (
                str(
                    Fraction(
                        sum(int(row["list_boundary_hits"]) for row in rows),
                        max(
                            1,
                            sum(
                                int(row["list_boundary_total"])
                                for row in rows
                            ),
                        ),
                    )
                )
            ),
            "protected_unit_violations": sum(
                int(row["protected_unit_violations"]) for row in rows
            ),
            "incomplete_endings": sum(
                int(row["incomplete_endings"]) for row in rows
            ),
            "orphan_beginnings": sum(
                int(row["orphan_beginnings"]) for row in rows
            ),
            "maximum_characters": max(
                int(row["maximum_characters"]) for row in rows
            ),
            "total_elapsed_milliseconds": round(
                sum(float(row["elapsed_milliseconds"]) for row in rows), 3
            ),
        }
    payload = {"corpus_size": len(CORPUS), "summary": summary, "results": results}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
