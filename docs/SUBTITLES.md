# Natural script-preserving subtitles

## Production policy

New results use
`conservative-subtitles-v8-syntax-guardrails-45chars-gapless`. The original script is
the only source of displayed text. ASR contributes timing observations only;
the syntax analyzer contributes boundary evidence only. Neither may rewrite,
correct, translate, normalize, delete, or insert displayed words.

Every final cue contains 1–45 visible characters including spaces and
punctuation. The old ten-word configuration field remains serialized for
backward compatibility but no longer forces a split: the character ceiling is
the actual hard publication constraint.

## Local syntax architecture

The primary English analyzer is spaCy 3.8 with the bundled
`en_core_web_sm 3.8.0` pipeline. It supplies POS tags, dependency relations,
lemmata, sentence boundaries, and named-entity spans. It is local, performs no
network request, and has no user-selectable model setting.

In the desktop application the Python/native parser runtime is prepared when
processing starts. The model is loaded lazily, once per process. Syntax is
computed before a Qt worker begins and stored in a bounded immutable cache keyed
by exact script text, exact character offsets, and token identities. This
avoids moving a BLAS-backed spaCy pipeline between Qt threads. Headless callers
load and reuse the same singleton directly.

If the packaged model cannot load, a deterministic standard-library fallback
is used. The result records `deterministic_fallback` plus a warning; fallback is
never reported as a full dependency parse.

Each parser token is mapped back to a source word with:

- exact text and character offsets;
- source token and timing references;
- lemma, POS, fine tag, dependency relation, and syntactic head;
- sentence/clause membership;
- function-word, particle, degree-modifier, and list membership flags;
- protected constituent identifiers.

Displayed text is always sliced from the exact script. It is never rebuilt
from parser tokens.

## Boundary priority and constituents

Every candidate boundary is classified as `required`, `preferred`, `neutral`,
or `forbidden`. Sentence transitions and genuine enumeration items are
required. Complete clause edges are preferred. A safe fallback edge is neutral.
A boundary inside a protected grammatical unit is forbidden.

The parser is a guardrail, not a segmenter. A dependency subtree ending at a
position does not create a cue. When an entire natural phrase is at most 45
display characters, neutral and preferred internal edges are ignored unless a
required list/sentence boundary is present. This protects general `X or not`
constructions and compact WH-clause complements such as an introductory
expression followed by `what`, `why`, `how`, `where`, `who`, or `which`.

The protected categories are:

- auxiliary + verb;
- verb + particle;
- verb + compact object;
- preposition + object;
- adjective + noun;
- compound noun;
- degree modifier + modified word;
- temporal connector;
- number + unit;
- multiword proper name;
- determiner + noun;
- subordinator + clause opening.

Dependency spans are protected only while they can coexist with the
45-character ceiling. Several individually valid spans can overlap into a
connected unit that is too long. A small deterministic DP then demotes the
least damaging internal edge from forbidden to discouraged. It does not use
literal sentence exceptions. Stable category weights and left-to-right
tie-breaking make the decision reproducible.

Genuine coordinated list items are detected from dependency coordination and
parallel punctuation structure. Repeated prepositions, determiners, verb forms,
and coordinated noun/prepositional phrases are structural evidence. The
complete start of every item is used, rather than an internal dependency head.
Accepted item boundaries are mandatory and the final conjunction remains with
its item. Ordinary introductory or subordinate-clause commas are not lists.

## Segmentation, repair, and layout

The order is fixed:

1. exact-script tokenization;
2. sentence and genuine-list detection;
3. local syntax analysis and protected-span detection;
4. required/preferred/neutral/forbidden boundary classification;
5. minimum-cue constrained dynamic-programming segmentation;
6. one bounded adjacent-neighbor repair pass;
7. display punctuation transformation;
8. one- or two-line layout;
9. gapless display timing;
10. strict validation;
11. publication to Preview, table, SRT, and export.

The DP comparison is lexicographic: valid paths with fewer semantic cues win
before parser score, speech-gap score, or visual balance. Required boundaries
cannot be crossed and forbidden boundaries cannot be selected. The remaining
score only chooses between equal-cue-count valid paths. No randomness is used.

Repair evaluates one adjacent window using the same legality and candidate
validator. There is no cascading three-cue or repeated repair cycle. It cannot
create an overlong cue, cross a sentence/list boundary, or split a protected
constituent. Line layout uses the same protected edges and avoids one-word
heads/tails where a legal alternative exists. A line break never creates a new
cue or timestamp.

## Exact source and display punctuation

The immutable source invariant is:

```text
"".join(block.source_text_exact for block in blocks) == exact_script_text
```

Only a separate display representation hides one ordinary terminal ASCII
period or terminal comma. Ellipses, Unicode ellipses, decimals, URLs, email
addresses, filenames, abbreviations, capitalization, spelling, and every source
character remain in the exact span. Preview and SRT both render the same stored
`display_lines`.

## Gapless timing

`apply_gapless_display_timing()` is the single timing policy for Preview, the
subtitle table, SRT, and universal export. For a non-final cue, display end is
the next cue start. At millisecond precision the SRT end is exactly one
millisecond before the next start. The final cue reaches cleaned-audio duration.
Observed word timing and cleaned WAV samples are never modified.

Required metrics are zero internal gaps, zero SRT gaps, zero overlap, and zero
maximum gap. Invalid cue ordering or millisecond collisions fail publication.

## Diagnostics and performance

The report records analyzer mode, parser initialization and parse time,
candidate/legal/discouraged/forbidden boundary counts, segmentation, repair,
line layout and total subtitle time. Final validation recalculates syntax
violations plus semantic cue count, unnecessary splits, required-boundary
misses, list-item internal splits, orphan beginnings, WH-clause and `or not`
splits, and low-confidence parser splits rather than trusting serialized
values.

Normal English acceptance corpora require zero for:

- forced syntax splits;
- auxiliary/verb, verb/particle, verb/object and preposition/object splits;
- adjective/noun, compound noun, degree-modifier and temporal-connector splits;
- number/unit and proper-name splits;
- orphan, incomplete-ending and list-merge violations.

Current Apple Silicon benchmark targets are a warm 250–500-word parse below
150 ms, segmentation/repair after parsing below 100 ms, total subtitle stage
preferably below one second and always below two seconds.

## Compatibility and limitations

The portable schema remains `subtitle_blocks.schema.v1`; the versioned policy
identifies v8 semantics. Valid v7/v6/v5/v4/v3/v2 documents remain readable
under their historical rules and are not silently relabelled.

The bundled small English model is statistical and can misparse unusual prose.
The conservative fallback is less capable and is exposed in diagnostics.
Non-English scripts do not yet have a production dependency model. A single
indivisible word longer than 45 characters fails safely. This stage does not
add translation, LLM correction, cloud AI, phoneme alignment, or editor-native
project generation.
