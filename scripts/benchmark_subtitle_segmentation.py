#!/usr/bin/env python3
"""Run Stage 14.3 bounded grammar/list benchmarks without audio or ASR."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import SubtitleSettings
from larp_audio_mvp.core.contracts import (
    AlignedScriptWord,
    AlignmentMatchType,
    ScriptTokenKind,
    SubtitleDocument,
    TimingStatus,
)
from larp_audio_mvp.core.errors import SubtitleCoverageError
from larp_audio_mvp.exports import render_srt
from larp_audio_mvp.subtitles.chunker import DeterministicSubtitleChunker
from larp_audio_mvp.subtitles.display import subtitle_display_text
from larp_audio_mvp.subtitles.policy import (
    SEMANTIC_SUBTITLE_POLICY_VERSION,
    semantic_boundary_signals,
    word_keys,
)
from larp_audio_mvp.subtitles.repair import repair_orphan_ranges
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing
from larp_audio_mvp.subtitles.validation import (
    SUBTITLE_SCHEMA_VERSION,
    calculate_subtitle_diagnostics,
)


def synthetic_alignment(word_count: int, corpus: str):
    words = _corpus_words(word_count, corpus)
    text = " ".join(words)
    tokens = tokenize_script(text)
    word_tokens = tuple(
        token for token in tokens if token.kind is ScriptTokenKind.WORD
    )
    words = tuple(
        AlignedScriptWord(
            script_word_index=index,
            token_index=token.token_index,
            exact_text=token.exact_text,
            char_start=token.char_start,
            char_end=token.char_end,
            cleaned_start_sample=index * 400,
            cleaned_end_sample=index * 400 + 300,
            original_start_sample=index * 400,
            original_end_sample=index * 400 + 300,
            timing_status=TimingStatus.OBSERVED,
            match_type=AlignmentMatchType.EXACT,
            matched_recognition_indices=(index,),
            text_similarity=1,
            alignment_score=1,
            asr_confidence=1,
        )
        for index, token in enumerate(word_tokens)
    )
    return SimpleNamespace(
        aligned_words=words,
        script=SimpleNamespace(exact_text=text),
        tokens=tokens,
        edit_map=SimpleNamespace(
            output_total_samples=word_count * 400 + 1_000,
            source_total_samples=word_count * 400 + 1_000,
        ),
        sample_rate=1_000,
    )


def _corpus_words(word_count: int, corpus: str) -> list[str]:
    patterns = {
        "list_heavy": (
            "at", "childbirth,", "at", "weak", "pelvic", "floors,",
            "at", "that", "second", "cup", "of", "coffee.",
        ),
        "adjective_heavy": (
            "The", "weak", "pelvic", "floors", "support", "natural",
            "movement", "and", "new", "baby", "hairs", "appear.",
        ),
        "pronoun_heavy": (
            "They", "helped", "her", "and", "told", "him", "to",
            "protect", "you", "while", "it", "improves", "them.",
        ),
    }
    if corpus in patterns:
        pattern = patterns[corpus]
        return [pattern[index % len(pattern)] for index in range(word_count)]
    result = []
    for index in range(word_count):
        base = f"extraordinaryword{index}" if corpus == "long_words" else f"word{index}"
        suffix = ""
        if corpus == "punctuation" and index % 9 == 8:
            suffix = ","
        elif corpus == "periods" and index % 9 == 8:
            suffix = "."
        elif corpus == "ellipses" and index % 9 == 8:
            suffix = "..." if index % 18 == 8 else "…"
        result.append(base + suffix)
    return result


def benchmark_document(alignment, boundaries, settings, chunker):
    """Build a valid synthetic document without benchmarking alignment itself."""

    blocks = tuple(
        chunker._build_block(
            alignment,
            start,
            end,
            block_index=index,
            settings=settings,
        )
        for index, (start, end) in enumerate(boundaries, start=1)
    )
    diagnostics = calculate_subtitle_diagnostics(
        blocks=blocks,
        total_script_words=len(alignment.aligned_words),
        unresolved_script_words=0,
        interpolated_script_words=0,
        sample_rate=alignment.sample_rate,
        settings=settings,
        document_warnings=(),
        exact_script_text=alignment.script.exact_text,
        grammar_policy=True,
        layout_policy=True,
    )
    return SubtitleDocument(
        schema_version=SUBTITLE_SCHEMA_VERSION,
        source_alignment_schema_version="alignment.schema.v2",
        source_alignment_sha256="a" * 64,
        script_sha256=hashlib.sha256(
            alignment.script.exact_text.encode("utf-8")
        ).hexdigest(),
        script_encoding="utf-8",
        script_has_bom=False,
        exact_script_text=alignment.script.exact_text,
        sample_rate=alignment.sample_rate,
        cleaned_total_samples=alignment.edit_map.output_total_samples,
        original_total_samples=alignment.edit_map.source_total_samples,
        configuration_snapshot=settings.snapshot(),
        blocks=blocks,
        diagnostics=diagnostics,
        warnings=(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, nargs="+", default=(300, 600, 2_000))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = []
    for corpus in (
        "plain",
        "punctuation",
        "periods",
        "ellipses",
        "long_words",
        "list_heavy",
        "adjective_heavy",
        "pronoun_heavy",
    ):
        for count in args.words:
            alignment = synthetic_alignment(count, corpus)
            settings = SubtitleSettings()
            chunker = DeterministicSubtitleChunker()
            display_started = perf_counter()
            subtitle_display_text(alignment.script.exact_text)
            display_ms = (perf_counter() - display_started) * 1_000
            total_started = perf_counter()
            segmentation_started = perf_counter()
            try:
                boundaries, metrics = chunker._segment_with_metrics(
                    alignment, settings
                )
            except SubtitleCoverageError:
                elapsed_ms = (perf_counter() - total_started) * 1_000
                results.append(
                    {
                        "corpus": corpus,
                        "words": count,
                        "status": "safely_rejected_over_45_character_atom",
                        "period_display_transformation_milliseconds": round(display_ms, 3),
                        "elapsed_milliseconds": round(elapsed_ms, 3),
                    }
                )
                continue
            segmentation_elapsed_ms = (perf_counter() - segmentation_started) * 1_000
            keys = word_keys(alignment.aligned_words)
            exact_words = tuple(word.exact_text for word in alignment.aligned_words)
            signals = semantic_boundary_signals(
                alignment.script.exact_text,
                alignment.aligned_words,
                keys,
            )

            def candidate_is_valid(start: int, end: int) -> bool:
                if end < len(alignment.aligned_words) and end in signals.grammar.syntax.forbidden_boundaries:
                    return False
                return chunker._candidate(
                    alignment,
                    start,
                    end,
                    settings,
                    keys=keys,
                    exact_words=exact_words,
                    signals=signals,
                ) is not None

            boundaries, _repair_metrics = repair_orphan_ranges(
                boundaries,
                keys=keys,
                protected=signals.grammar.protected,
                mandatory=frozenset(signals.sentence | signals.grammar.list_item),
                candidate_is_valid=candidate_is_valid,
            )
            construction_started = perf_counter()
            document = benchmark_document(alignment, boundaries, settings, chunker)
            construction_ms = (perf_counter() - construction_started) * 1_000
            timing_started = perf_counter()
            apply_gapless_display_timing(document)
            timing_ms = (perf_counter() - timing_started) * 1_000
            srt_started = perf_counter()
            render_srt(document)
            srt_ms = (perf_counter() - srt_started) * 1_000
            total_ms = (perf_counter() - total_started) * 1_000
            results.append(
                {
                    "corpus": corpus,
                    "words": count,
                    "status": "success",
                    "blocks": len(boundaries),
                    "list_item_count": document.diagnostics.list_item_count,
                    "list_item_merge_violation_count": document.diagnostics.list_item_merge_violation_count,
                    "protected_unit_count": document.diagnostics.protected_unit_count,
                    "protected_unit_violation_count": document.diagnostics.protected_unit_violation_count,
                    "maximum_display_characters": document.diagnostics.maximum_display_characters,
                    "orphan_fragment_count": document.diagnostics.orphan_fragment_count,
                    "incomplete_ending_count": document.diagnostics.incomplete_ending_count,
                    "trailing_comma_violation_count": document.diagnostics.trailing_comma_violation_count,
                    "two_line_cue_count": document.diagnostics.two_line_cue_count,
                    "maximum_plain_characters": document.diagnostics.maximum_plain_characters,
                    "maximum_render_line_characters": document.diagnostics.maximum_render_line_characters,
                    "candidate_evaluations": metrics.candidate_evaluations,
                    "syntax_analyzer_mode": metrics.syntax_analyzer_mode,
                    "parser_initialization_milliseconds": round(metrics.parser_initialization_nanoseconds / 1_000_000, 3),
                    "syntax_parse_milliseconds": round(metrics.syntax_parse_nanoseconds / 1_000_000, 3),
                    "candidate_boundary_count": metrics.candidate_boundary_count,
                    "legal_boundary_count": metrics.legal_boundary_count,
                    "discouraged_boundary_count": metrics.discouraged_boundary_count,
                    "forbidden_boundary_count": metrics.forbidden_boundary_count,
                    "forced_syntax_split_count": metrics.forced_syntax_split_count,
                    "auxiliary_verb_split_count": document.diagnostics.auxiliary_verb_split_count,
                    "verb_particle_split_count": document.diagnostics.verb_particle_split_count,
                    "verb_object_split_count": document.diagnostics.verb_object_split_count,
                    "preposition_object_split_count": document.diagnostics.preposition_object_split_count,
                    "adjective_noun_split_count": document.diagnostics.adjective_noun_split_count,
                    "compound_noun_split_count": document.diagnostics.compound_noun_split_count,
                    "degree_modifier_split_count": document.diagnostics.degree_modifier_split_count,
                    "temporal_connector_split_count": document.diagnostics.temporal_connector_split_count,
                    "number_unit_split_count": document.diagnostics.number_unit_split_count,
                    "proper_name_split_count": document.diagnostics.proper_name_split_count,
                    "tokenization_milliseconds": round(
                        metrics.tokenization_nanoseconds / 1_000_000, 3
                    ),
                    "candidate_boundary_detection_milliseconds": round(
                        metrics.candidate_boundary_detection_nanoseconds / 1_000_000, 3
                    ),
                    "orphan_repair_milliseconds": round(
                        metrics.orphan_repair_nanoseconds / 1_000_000, 3
                    ),
                    "line_layout_milliseconds": round(
                        metrics.line_layout_nanoseconds / 1_000_000, 3
                    ),
                    "period_display_transformation_milliseconds": round(display_ms, 3),
                    "segmentation_milliseconds": round(
                        metrics.segmentation_nanoseconds / 1_000_000, 3
                    ),
                    "segmentation_call_milliseconds": round(segmentation_elapsed_ms, 3),
                    "block_construction_milliseconds": round(construction_ms, 3),
                    "timing_postprocessing_milliseconds": round(timing_ms, 3),
                    "srt_serialization_milliseconds": round(srt_ms, 3),
                    "total_subtitle_stage_milliseconds": round(total_ms, 3),
                }
            )
    payload = {
        "policy_version": SEMANTIC_SUBTITLE_POLICY_VERSION,
        "results": results,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
