# ADR-002: Bundled local English syntax analyzer

- Status: amended by Stage 14.6
- Date: 2026-07-24

## Context

The Stage 14.3/14.4 subtitle policy used bounded lexical tables and local
shape heuristics. That was fast, but it could not reliably distinguish a verb
particle, a compound noun, a prepositional object, or a degree modifier in an
unseen sentence. Adding more reported phrases would overfit the test corpus
and would violate the product requirement for a general syntax-aware policy.

## Decision

The primary analyzer is `spaCy >=3.8.14,<3.9` with the pinned
`en_core_web_sm 3.8.0` English pipeline. The model is installed as a normal
application dependency and collected into the PyInstaller application. It is
loaded lazily once per process and reused. No runtime download, model picker,
network request, Python installation, or Terminal action is allowed.

`en_core_web_sm` supplies POS tags, fine-grained tags, dependency relations,
sentence boundaries, lemmata and named-entity spans. Analyzer tokens are
mapped back to immutable original-script character spans; displayed subtitle
text is always sliced from the original script and is never reconstructed
from spaCy tokens.

A deterministic standard-library fallback is retained for controlled recovery
when the bundled pipeline cannot load. Fallback mode is reported explicitly
in subtitle diagnostics and is not represented as full parsing.

Stage 14.6 restricts the parser to guardrail evidence. Parser subtrees may
forbid unsafe boundaries, protect grammatical spans, and help validate clauses
and genuine lists. They do not independently propose extra cues. Segmentation
first minimizes cue count under sentence/list, 45-character, and grammar
constraints; parser and pause scores only break ties between paths with the
same cue count. This amendment corrects the Stage 14.5 cost-first regression
without removing the local parser dependency.

## Dependency and licensing assessment

| Item | Purpose | Version | License | Packaging impact |
|---|---|---:|---|---|
| spaCy | POS/dependency/NER runtime | `>=3.8.14,<3.9` | MIT | Native wheels and transitive runtime libraries; collected by PyInstaller |
| en_core_web_sm | English statistical pipeline | `3.8.0` | MIT | Model data bundled in `.app`; expected tens of MB uncompressed |

The standard library and the existing project dependencies do not provide a
production-quality English dependency parser. spaCy is therefore a deliberate
runtime dependency rather than a convenience dependency. The model version is
compatible with spaCy 3.8, optimized for CPU, and does not require PyTorch.

The macOS and Windows PyInstaller specifications must collect both packages.
Runtime license collection must include spaCy, its transitive packages and the
model metadata/license. Package size, cold initialization, warm parsing and
offline packaged execution are release gates. A future upgrade requires the
same license, compatibility, performance, privacy and packaged-app checks.

## Consequences

- English scripts receive a real dependency parse as structural validation,
  without reported-phrase exceptions or parser-driven cue proliferation.
- Statistical parsing can still be wrong; the segmenter therefore uses
  conservative generic relations, validates final boundaries and exposes
  forced-split metrics.
- The application grows materially and cold startup of the subtitle stage is
  slower. Lazy singleton initialization keeps normal GUI startup unaffected.
- Non-English input uses the controlled fallback until a separately approved
  multilingual architecture exists.

## Sources

- spaCy model packaging and native-import guidance:
  https://spacy.io/usage/models
- spaCy source and MIT license:
  https://github.com/explosion/spaCy
- Official model releases:
  https://github.com/explosion/spacy-models/releases
