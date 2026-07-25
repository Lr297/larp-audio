# Script-preserving script-to-ASR alignment

## Scope and terminology

Stage 8/8.1 reads an exact UTF-8 script, the existing `recognition.json`, and the existing `edit_map.json`, then creates `alignment.json`. This is deterministic **script-to-ASR word alignment**: it aligns script word tokens to Faster-Whisper word observations and transfers timing evidence. It is not phoneme-level acoustic forced alignment and does not use WhisperX, Montreal Forced Aligner, a phoneme model, or another Whisper run.

The original script is the only source of output text. ASR text is comparison evidence only. It is never substituted into `exact_text`, punctuation, whitespace, or any future subtitle text.

## Exact script ingestion and tokens

The reader hashes the exact source bytes with SHA-256, accepts strict UTF-8 with an optional UTF-8 BOM, and reads bytes directly so Python universal-newline conversion cannot change CRLF to LF. The BOM is recorded in `has_bom` and removed only from the decoded `exact_text`. Metadata records encoding, exact decoded character count, and logical line count. Empty and whitespace-only scripts fail explicitly.

The tokenizer is independent of ASR and produces three token kinds:

- `word`: Unicode letter/mark/number sequences; an internal apostrophe or dash is retained when surrounded by word characters;
- `punctuation`: every other non-whitespace code point;
- `whitespace`: an exact contiguous run, including repeated spaces, tabs, CRLF, LF, or CR.

Every token stores half-open character offsets. Two invariants are validated:

```text
script_text[token.char_start:token.char_end] == token.exact_text
"".join(token.exact_text for token in tokens) == script_text
```

Only word tokens participate in alignment. Punctuation and whitespace remain exact material for the next stage and receive no fabricated ASR words.

## Comparison normalization

`comparison_key` is never a display value. It uses deterministic NFKC normalization, `casefold`, maps typographic apostrophes to `'`, maps dash variants to `-`, and removes only outer punctuation, symbols, and whitespace. Internal apostrophes and hyphens remain. There is no stemming, translation, transliteration, number expansion, grammar repair, phonetic guess, semantic match, or LLM.

For example, exact `Don’t` may compare through `don't`, but alignment output continues to contain exact `Don’t`.

## Weighted dynamic programming

The engine uses global O(n × m) dynamic programming over script words and ASR observations. It supports:

- 1:1 exact surface match;
- 1:1 normalized-key match;
- conservative 1:1 fuzzy match;
- script omission and ASR insertion gaps;
- explicit substitution;
- bounded one-script-to-two-ASR and two-script-to-one-ASR structural match.

Fuzzy similarity is normalized Levenshtein similarity implemented with the standard library. It is disabled below `min_fuzzy_token_length` (default 4) and must meet `fuzzy_threshold` (default 0.84). This prevents aggressive matching of short words such as `a`, `I`, `я`, `в`, `і`, or `to`.

The split/merge operation is deliberately bounded to 1:2 and 2:1. It compares structural keys after removing internal apostrophe/hyphen connectors. It does not search arbitrary phrases.

The DP table is allocated only when `(script_words + 1) × (ASR_words + 1)` is no greater than `max_dp_cells`. Exceeding the limit returns `ALIGNMENT_DP_LIMIT_EXCEEDED`; it never silently allocates unbounded memory.

### Stable scoring and tie-breaking

Operation rewards/penalties are fixed integers. At equal total score the stable priority is:

1. exact;
2. normalized;
3. fuzzy;
4. split/merge;
5. substitution;
6. script deletion;
7. ASR insertion.

Traceback proceeds from the start of both sequences. No random value, unordered collection iteration, clock, or generated identifier affects the result.

## Match type versus timing status

`match_type` describes textual sequence evidence:

- `exact` — exact script/trimmed-ASR surface;
- `normalized` — comparison keys are equal;
- `fuzzy` — bounded similarity passed the threshold;
- `one_script_to_many_asr` — one script token matched two ASR observations;
- `many_script_to_one_asr` — two script tokens matched one ASR observation;
- `substitution` — both sequences consumed, but text evidence was not reliable;
- `interpolated` — the word had no reliable direct match and received conservative timing between anchors;
- `unresolved` — no reliable text match.

`timing_status` separately states timing provenance:

- `observed` — direct ASR interval or the union of two direct ASR intervals;
- `distributed` — one ASR interval partitioned between two script words;
- `interpolated` — a gap partitioned between unmatched script words;
- `unresolved` — no timing was assigned.

A substitution has unresolved timing and no accepted ASR index. The considered ASR observation is copied to `rejected_asr_evidence` with reason `substitution_not_accepted`; it is never left in `matched_recognition_indices`.

## Timing rules and dual timelines

Integer sample indices are authoritative. A 1:1 match receives the ASR cleaned interval. One script word to two ASR observations receives their union. Two script words to one ASR observation divide the complete interval proportionally to comparison-key length.

Distribution first reserves one sample per word. Remaining samples are allocated by integer floor of the weight ratio; residual samples go to earlier words in script order. Consequently ranges are positive, adjacent, non-overlapping, and exactly cover the original interval without creating or losing samples. If the source interval has fewer samples than words, no invalid range is invented.

All original-timeline boundaries are computed using the existing binary-search `TimelineMapper.target_to_source`. Alignment never reimplements pause-offset arithmetic. A cleaned range spanning a cut can therefore map to a larger original range containing the removed pause, exactly as the edit map specifies.

## Conservative interpolation

An unresolved run is interpolated only when:

- a reliable exact/normalized/split-merge anchor exists immediately before and after it;
- the run length does not exceed `max_interpolation_words`;
- the cleaned gap is positive and does not exceed `max_interpolation_gap_ms`;
- the gap contains at least one sample per missing word;
- allocation creates no overlap.

Fuzzy matches and substitutions are not reliable interpolation anchors. Leading and trailing unmatched words are never extrapolated. Interpolated ranges use the same length-weighted integer allocation, have null ASR confidence, empty `matched_recognition_indices`, no accepted operation id/score, and explicit left/right script-anchor indices. Any rejected ASR evidence considered before interpolation remains separately classified.

## Confidence, similarity, and score

- `asr_confidence` is the backend value for 1:1 or many-to-one timing. For one-to-many it is the minimum available confidence only when every contributing observation has a value; otherwise it is null. Zero is never substituted for missing confidence.
- `text_similarity` is exact normalized Levenshtein similarity for an accepted fuzzy match, or 1 for structurally equal accepted matches. Rejected/unresolved/interpolated words do not claim an accepted similarity.
- `alignment_score` is the documented accepted-match policy score: 1 exact, 0.9 normalized, fuzzy similarity for fuzzy, and 0.8 split/merge. It is not a statistical probability. Rejected/unresolved/interpolated words store null.
- `timing_status` is the independent provenance of the interval.

## Input compatibility

Before alignment, strict readers and domain contracts validate both JSON schemas, positive and monotonic word intervals, sample bounds, sample rates, cleaned/original totals, edit-map partitions, and all derived rational seconds. Every recognition original boundary must equal a fresh mapping of its cleaned boundary through the provided edit map.

When present, both `cleaned_audio_sha256` and Stage 7's `edit_map_output_sha256` are compared with the edit-map target-audio hash. Stage 7 does not currently record a hash of the JSON map file itself, so Stage 8 does not pretend that such a fingerprint exists. The strict map schema, partition, totals, target hash, and every mapped word boundary are still revalidated. No STT or audio processing is rerun.

## ASR provenance classification

Every recognition index is classified exactly once:

1. **Accepted match** — appears in `matched_recognition_indices` and actually determines the word's accepted `match_type` and timing. Exact/normalized/fuzzy use one index; one-to-many uses a consecutive range; many-to-one may repeat one index across multiple script words only inside one validated `alignment_operation_id` group.
2. **Unmatched ASR observation** — appears once in `unmatched_asr_words`; the DP treated it as an insertion and it was not used as comparison evidence.
3. **Rejected ASR evidence** — appears once in `rejected_asr_evidence`; it participated in a substitution that was not accepted or in a many-to-one operation whose interval could not be distributed safely.

The three sets are disjoint and their union must equal `range(total_asr_words)`. `classified_asr_words` records the union size and `provenance_complete` is true only when the invariant holds.

Each rejected entry stores the original ASR text, cleaned/original sample bounds, confidence, rejection reason, related script-word indices, attempted match type, and attempted operation id. It is diagnostic evidence only and can never become display text. `matched_recognition_indices` therefore means only accepted evidence.

## Many-to-one grouping

Every accepted alignment operation receives a stable `alignment-op-NNNNNN` id. A many-script-to-one group shares one id and one ASR index. Its script indices are consecutive, its integer ranges are adjacent, and their deterministic length-weighted partition exactly covers the source ASR interval. If the ASR interval has fewer samples than script words, the operation is rejected: the ASR observation moves to `rejected_asr_evidence` with `timing_distribution_impossible`, and the script words remain unresolved or may later be conservatively interpolated.

## `alignment.json` schema version

Stage 8.1 writes `alignment.schema.v2`. V2 embeds the complete canonical `RecognitionResult` and `EditMap`, exact script metadata/tokens, canonical `AlignedScriptWord` records, unmatched observations, rejected evidence, recalculable diagnostics, warnings, and the sorted configuration snapshot. Embedding the existing canonical inputs lets a standalone reader re-run `TimelineMapper` checks rather than trust copied original times.

Stage 8 schema `"1"` is explicitly rejected with `UNSUPPORTED_ALIGNMENT_SCHEMA`. It lacks complete rejected-evidence classification and embedded map/recognition data, so automatic migration could invent provenance. Stage 8 logical scenarios remain supported by rerunning alignment from their original script, recognition, and edit-map inputs.

JSON uses UTF-8, preserved Unicode, sorted keys, two-space indentation, and one final LF. It is first written beside the destination as `.partial.json`, flushed/fsynced, then published with `os.replace`; temporary files are removed after success or failure.

## Strict reader validation

`read_alignment()` reconstructs the canonical contracts and then validates schema, exact UTF-8/BOM SHA-256, line/character counts, canonical reversible tokenization, word/token identity, every rational denominator/decimal, configuration snapshot, recognition and edit-map schemas, timeline totals/hashes, and every cleaned→original boundary through the existing `TimelineMapper`.

Accepted 1:1/one-to-many/many-to-one intervals are compared with embedded recognition observations. Operation groups, interpolation anchors/limits/weighted partitions, confidence provenance, monotonicity, bounds, and the complete disjoint ASR classification are checked. Malformed files produce only controlled alignment serialization/validation errors.

The reader recalculates all match counts, split/merge/substitution operation counts, unresolved/interpolated counts, unmatched/rejected/classified ASR counts, `provenance_complete`, and all coverage fractions. Stored diagnostics must equal the recalculated dataclass exactly; they are never repaired silently.

## Canonical aligned-word contract and future chunker

`AlignedScriptWord` is the only aligned original-script word contract. The historical `AlignedWord` name is a deprecated compatibility alias to the same class, not a second dataclass or semantic model. `AlignmentResult.aligned_words`, engine/service output, serializer, and reader all use `AlignedScriptWord`.

The unimplemented `SubtitleChunker` Protocol now accepts the whole validated `AlignmentResult`, preserving exact text, punctuation, whitespace, character offsets, timing provenance, rejected/unmatched evidence, and warnings. Stage 8.1 does not implement chunking.

## Coverage metrics and warnings

- `observed_timing_coverage` = script words with `timing_status=observed` / total script words. Distributed and interpolated words are intentionally excluded.
- `total_timing_coverage` = script words with any non-unresolved timing / total script words.
- `text_alignment_coverage` = script words with exact, normalized, fuzzy, or split/merge textual evidence / total script words. Substitutions and interpolated-only words are excluded.
- `split_merge_matches` counts split/merge operations; other match counters count script words.
- `rejected_asr_evidence_count`, `classified_asr_words`, and `provenance_complete` describe the v2 provenance partition.

Warnings are added when text or timing coverage is below the configured threshold, fuzzy or unresolved words exceed 20%, word counts differ significantly, or ASR has many explicit insertions. Low coverage is not hidden because downstream subtitle creation must be able to stop or require review instead of publishing invented timing.

## Known limitations and failure modes

- There is no acoustic or phoneme-level re-alignment; timing granularity cannot exceed the Stage 7 ASR observations.
- Only bounded 1:2 and 2:1 split/merge is supported.
- Numeric forms are not expanded (`12` and `twelve` do not match automatically).
- Repetition and highly divergent scripts can be ambiguous even with deterministic tie-breaking.
- O(n × m) is intentionally bounded and may reject very large inputs until a later windowed architecture is approved.
- Stage 8 v1 persisted files require deliberate re-alignment from their original three inputs; unsafe provenance migration is not attempted.
- Low coverage is a truthful result for diagnostics, not permission to create SRT.

Stage 8 does not create subtitle blocks, SRT, XML, GUI output, or modify audio/edit maps.
