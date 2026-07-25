#!/usr/bin/env python3
"""Create a privacy-safe semantic-subtitle acceptance summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.core.contracts import ScriptTokenKind
from larp_audio_mvp.pipeline.artifacts import read_processing_report
from larp_audio_mvp.subtitles.policy import sentence_boundary_positions
from larp_audio_mvp.subtitles.display import has_removable_terminal_period
from larp_audio_mvp.subtitles.serialization import read_subtitle_document
from larp_audio_mvp.subtitles.timing import apply_gapless_display_timing
from larp_audio_mvp.exports import subtitle_cues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, required=True)
    parser.add_argument("--processing-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = read_subtitle_document(args.blocks)
    tokens = tokenize_script(document.exact_script_text)
    words = tuple(token for token in tokens if token.kind is ScriptTokenKind.WORD)
    block_end_positions = {
        block.script_word_indices[-1] + 1 for block in document.blocks
    }
    mandatory = sentence_boundary_positions(document.exact_script_text, words)
    punctuation_violations = len(mandatory - block_end_positions)
    counts = tuple(block.word_count for block in document.blocks)
    exported = tuple(
        index for block in document.blocks for index in block.script_word_indices
    )
    display_lengths = tuple(len(block.display_text) for block in document.blocks)
    period_violations = sum(
        has_removable_terminal_period(block.display_text)
        for block in document.blocks
    )
    timing = apply_gapless_display_timing(document)
    cues = subtitle_cues(document)
    payload: dict[str, object] = {
        "policy_version": dict(document.configuration_snapshot)["policy_version"],
        "script_word_count": len(words),
        "subtitle_block_count": len(document.blocks),
        "minimum_words_per_block": min(counts),
        "maximum_words_per_block": max(counts),
        "average_words_per_block": {
            "numerator": document.diagnostics.average_words_per_block.numerator,
            "denominator": document.diagnostics.average_words_per_block.denominator,
        },
        "one_word_blocks": sum(count == 1 for count in counts),
        "two_word_blocks": sum(count == 2 for count in counts),
        "three_to_five_word_blocks": sum(3 <= count <= 5 for count in counts),
        "six_to_ten_word_blocks": sum(6 <= count <= 10 for count in counts),
        "one_word_percentage": round(
            100 * sum(count == 1 for count in counts) / len(counts), 3
        ),
        "two_word_percentage": round(
            100 * sum(count == 2 for count in counts) / len(counts), 3
        ),
        "three_to_five_word_percentage": round(
            100 * sum(3 <= count <= 5 for count in counts) / len(counts), 3
        ),
        "six_to_ten_word_percentage": round(
            100 * sum(6 <= count <= 10 for count in counts) / len(counts), 3
        ),
        "punctuation_boundary_violations": punctuation_violations,
        "list_boundary_violations": punctuation_violations,
        "complete_word_coverage": exported == tuple(range(len(words))),
        "exact_text_coverage": str(document.diagnostics.text_coverage),
        "timing_coverage": str(document.diagnostics.timing_coverage),
        "minimum_display_characters": min(display_lengths),
        "maximum_display_characters": max(display_lengths),
        "terminal_period_violations": period_violations,
        "ellipsis_block_count": sum(
            "..." in block.display_text or "…" in block.display_text
            for block in document.blocks
        ),
        "internal_gap_count": sum(
            left.display_end_sample != right.display_start_sample
            for left, right in zip(timing, timing[1:])
        ),
        "srt_gap_count": sum(
            right.start_milliseconds - left.end_milliseconds != 1
            for left, right in zip(cues, cues[1:])
        ),
        "overlap_count": sum(
            left.display_end_sample > right.display_start_sample
            for left, right in zip(timing, timing[1:])
        ),
        "final_display_end_sample": timing[-1].display_end_sample,
        "cleaned_total_samples": document.cleaned_total_samples,
        "list_item_count": document.diagnostics.list_item_count,
        "list_item_merge_violation_count": document.diagnostics.list_item_merge_violation_count,
        "protected_unit_count": document.diagnostics.protected_unit_count,
        "protected_unit_violation_count": document.diagnostics.protected_unit_violation_count,
        "adjective_noun_split_count": document.diagnostics.adjective_noun_split_count,
        "verb_object_split_count": document.diagnostics.verb_object_split_count,
        "phrasal_verb_split_count": document.diagnostics.phrasal_verb_split_count,
        "preposition_object_split_count": document.diagnostics.preposition_object_split_count,
        "number_unit_split_count": document.diagnostics.number_unit_split_count,
        "product_name_split_count": document.diagnostics.product_name_split_count,
        "orphan_fragment_count": document.diagnostics.orphan_fragment_count,
        "incomplete_ending_count": document.diagnostics.incomplete_ending_count,
        "trailing_period_violation_count": document.diagnostics.trailing_period_violation_count,
        "trailing_comma_violation_count": document.diagnostics.trailing_comma_violation_count,
        "three_line_cue_count": document.diagnostics.three_line_cue_count,
        "empty_line_count": document.diagnostics.empty_line_count,
        "maximum_plain_characters": document.diagnostics.maximum_plain_characters,
        "maximum_render_line_characters": document.diagnostics.maximum_render_line_characters,
        "cue_count": document.diagnostics.cue_count,
        "two_line_cue_count": document.diagnostics.two_line_cue_count,
        "forced_syntax_split_count": document.diagnostics.forced_syntax_split_count,
        "auxiliary_verb_split_count": document.diagnostics.auxiliary_verb_split_count,
        "verb_particle_split_count": document.diagnostics.verb_particle_split_count,
        "compound_noun_split_count": document.diagnostics.compound_noun_split_count,
        "degree_modifier_split_count": document.diagnostics.degree_modifier_split_count,
        "temporal_connector_split_count": document.diagnostics.temporal_connector_split_count,
        "proper_name_split_count": document.diagnostics.proper_name_split_count,
    }
    if args.processing_report:
        report = read_processing_report(args.processing_report)
        metrics = dict(report.metrics)
        payload["subtitle_segmentation_milliseconds"] = metrics.get(
            "subtitle_segmentation_milliseconds"
        )
        payload["subtitle_total_milliseconds"] = metrics.get(
            "subtitle_total_milliseconds"
        )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
