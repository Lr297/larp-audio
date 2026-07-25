# Test strategy

## 1. Quality objectives

The test program must prove five properties:

1. no protected spoken word is cut;
2. all cleaned timings are sample-accurate and mutually consistent;
3. displayed text is derived only from the original script; v4 may hide only a contextually identified terminal ASCII period while retaining its exact source span;
4. required artifacts import and relink on supported applications/platforms;
5. packaged processing is local, recoverable, and self-contained.

Exact numerical thresholds must be fixed in ADRs before implementation. Until then, tests should collect boundary error, alignment coverage, real-time factor, peak RSS, artifact size, and import deviations.

## 2. Test layers

| Layer | Purpose | Runs when |
|---|---|---|
| Unit | Algorithms, validators, serializers, state transitions | Every change |
| Property/invariant | Time maps, spans, quantization, determinism | Every change |
| Golden | Stable WAV/SRT/JSON/XML output | Every change |
| Contract | FFmpeg/STT/export adapter behavior | Adapter changes |
| Integration | Full headless pipeline with real bundled tools | Every merge / nightly |
| Corpus benchmark | Accuracy, naturalness, performance | Model/audio changes and release |
| NLE acceptance | Actual Premiere/Resolve import/reopen | Release candidate |
| Packaging clean-room | Installer, signing, offline, recovery | Release candidate |
| CapCut | Safe import and disposable experimental draft | Relevant release/profile |

## 3. Fixture strategy

### 3.1 Synthetic fixtures

Generate short deterministic PCM/WAV fixtures with known sample boundaries:

- silence before, between, and after words;
- pauses exactly below, at, and above thresholds;
- several removable pauses in one file;
- click-prone discontinuities and nonzero room tone;
- breaths, sibilants, plosives, fades, and low-level tails;
- mono/stereo and 44.1/48/96 kHz inputs;
- corrupt/truncated/unsupported containers;
- zero-length and all-silence inputs.

Synthetic fixtures prove arithmetic and signal policy but cannot prove perceived naturalness.

### 3.2 Licensed real corpus

Create a versioned, rights-cleared corpus dominated by ElevenLabs-style voiceovers:

- supported languages and accents;
- multiple voices, speeds, emotional delivery, and audio qualities;
- normal and intentionally long pauses;
- breaths and expressive sentence endings;
- numbers, currencies, dates, acronyms, URLs, and mixed-language phrases;
- skipped words, inserted words, repeats, retakes, and partial words;
- repeated identical phrases in different locations.

Each case should contain original audio, exact script, human word/pause boundary annotations, expected mismatch labels, and permitted/forbidden cut regions.

### 3.3 Editor fixtures

Use tiny redistributable WAV assets with Unicode and reserved characters in filenames, plus expected Premiere/Resolve project observations. Do not use customer media in fixtures.

## 4. Unit tests

### 4.1 Tokenizer and script fidelity

- exact character spans and round-trip source slices;
- Cyrillic, Latin diacritics, mixed scripts, CJK, RTL, emoji;
- smart quotes, apostrophes, em/en dash, punctuation before closing quote;
- multiple spaces, tabs, newlines, NBSP;
- abbreviations, decimals, dates, currencies, units, URLs, emails;
- long tokens, punctuation-only tokens, empty/whitespace-only script;
- case/punctuation/spelling never sourced from ASR.

### 4.2 Alignment

- exact, fuzzy, substitution, insertion, omission, repetition, ambiguity;
- many-to-many number/acronym matches;
- repeated phrases and long resync distances;
- zero/negative/nonmonotonic/overlapping ASR timestamps rejected;
- observed vs interpolated timing kept distinct;
- confidence threshold behavior;
- useful regression cases migrated from `engine/alignment/test_align.py:29-285`.

### 4.3 Pause planning

- threshold boundaries in samples;
- retained pause calculation;
- no cut intersects protected word plus guard;
- low-confidence region produces no-cut warning;
- breath/music/room-tone policy;
- leading/trailing trim separate from internal pause policy;
- neighboring or nested silence candidates merge deterministically;
- transitions never produce negative or overlapping ranges.

### 4.4 Edit map and remapping

Property tests must establish:

- source spans are ordered, disjoint, and exhaustive;
- output spans are contiguous and monotonic;
- sum of output lengths equals rendered sample count;
- mapping inside kept spans is reversible;
- removed interior times have an explicit mapping status, not a fabricated point;
- multiple cuts shift later words by exactly cumulative removed samples;
- sample-to-ms and sample-to-frame conversion follows documented integer rules;
- very long files do not overflow or drift.

### 4.5 Subtitle chunker

- below/at/above word, character, line, CPS, and duration limits;
- one-word and orphan tails;
- sentence/paragraph/pause/clause/conjunction priorities;
- no split in protected lexical groups;
- unsatisfiable constraints produce stable warning codes;
- cue intervals monotonic, nonoverlapping, within audio duration;
- omitted/inserted/repeated policies;
- deterministic byte-identical results.

### 4.6 Serializers and paths

- SRT `HH:MM:SS,mmm`, indices from 1, UTF-8, blank separators;
- XML escaping of `& < >`, quotes, Cyrillic, emoji;
- POSIX, Windows drive, UNC, long paths, spaces, `#`, `%`;
- traversal and forbidden absolute paths rejected in portable packages;
- JSON schema/version validation and stable ordering;
- archive normalization and checksums.

### 4.7 Job state machine

- every allowed/forbidden transition;
- cancellation at every stage;
- interrupted job classification;
- recovery and schema migration;
- no final artifact is visible before validation/atomic publish;
- logs are redacted.

## 5. Adapter contract tests

### FFmpeg/ffprobe

- app resolves bundled absolute paths with an empty `PATH`;
- probe schema covers expected formats;
- streaming decode and WAV render;
- corrupt input and nonzero exit handling;
- progress and cancellation without pipe deadlock;
- exact FFmpeg version/configure flags and forbidden GPL/nonfree audit.

### Local STT

- stable machine-readable output schema;
- language/model metadata and word confidence when available;
- empty audio, all silence, noise, long file, corrupt model;
- process cancellation and crash isolation;
- identical adapter semantics on all supported targets.

### Filesystem/model store

- read-only input, unwritable output, low disk, interrupted copy/download;
- wrong model hash/signature and rollback;
- application relocation and Unicode paths;
- staging cleanup never deletes user source/final files.

## 6. Golden tests

For every golden fixture, store:

- source audio/script hashes;
- policy/model/tool versions;
- expected edit map;
- expected cleaned WAV sample count and selected waveform windows;
- expected aligned words/cues;
- exact SRT;
- canonicalized Premiere XML and Resolve FCPXML;
- manifest/checksums.

Golden updates require a reviewed reason and before/after metric report. Never bulk-accept changed audio goldens.

## 7. End-to-end headless acceptance

Given only an input audio file, original script, packaged tools/model, and output directory:

1. run with network blocked;
2. complete without system Python/FFmpeg/model;
3. create all required artifacts with exact filenames;
4. verify every hash/schema;
5. compare output duration to edit-map invariant;
6. verify no forbidden cut region was removed;
7. reconstruct displayed cue text from original script spans;
8. rerun and prove deterministic outputs except explicitly excluded metadata;
9. cancel and force-kill at each stage, then verify recovery.

## 8. Audio quality acceptance

Automated checks:

- no discontinuity/click above an agreed splice metric;
- no cut inside annotated word/phoneme safety regions;
- output loudness/peak/channel layout remains within policy;
- pause durations match policy tolerance;
- no unexpected leading/trailing trim;
- no sample-count disagreement.

Human listening panel:

- blind compare original vs cleaned around each edit;
- label clipped phoneme, unnatural cadence, breath damage, click, or acceptable;
- require zero clipped-word findings in the release corpus;
- use adjudication for disputed expressive-pause cases.

## 9. STT/model benchmark

Report by platform, language, voice, and duration:

- WER as a diagnostic, not the only success metric;
- script-token alignment coverage and ambiguity rate;
- median/P95 word boundary error against human annotations;
- forbidden-cut false positive and missed-long-pause rates;
- real-time factor, cold start, peak RSS, model load time;
- installer/model size.

Choose the model only after thresholds pass on Windows x64, macOS arm64, and macOS x86_64.

## 10. Premiere and Resolve release gate

Matrix dimensions:

- supported Premiere versions on Windows/macOS;
- supported Resolve versions on Windows/macOS;
- 24/25/30 and approved 1000/1001 rates;
- Unicode/reserved filenames;
- mono/stereo and approved WAV sample rates.

For each profile:

1. validate XML syntax;
2. validate FCPXML against the selected DTD;
3. import on a clean project;
4. confirm one online cleaned WAV at time zero;
5. confirm sequence rate and exact tail within defined frame tolerance;
6. import SRT separately and compare cue text/timing;
7. save/reopen or round-trip export;
8. record translation warnings.

DTD validity is required but not sufficient.

## 11. CapCut tests

### Safe package

- fixed contents, hashes, no absolute paths;
- UTF-8 SRT imports on CapCut Desktop Windows/macOS;
- WAV and SRT remain manually editable;
- exporter never accesses CapCut draft directories.

### Experimental draft

- disposable OS profile/library only;
- exact supported CapCut version/schema fingerprint;
- creates a new draft, never mutates an existing one;
- simulated interruption before atomic publish;
- reopen verification;
- unknown version/schema fails closed;
- backup/restore test.

## 12. Packaging and clean-room matrix

| Target | Installation | Runtime | Security/recovery |
|---|---|---|---|
| macOS arm64 | Downloaded signed/notarized DMG, no dev tools | Offline full job | Gatekeeper, quarantine, cancel, crash, low disk |
| macOS x86_64 | Same | RTF/RSS benchmark | Same |
| Windows x64 | Signed offline installer, no elevation if promised | Offline full job, empty `PATH` | Authenticode, uninstall/update, process tree, AV scan |
| Windows ARM64 experimental | Build/benchmark only | No v1 promise | Separate ADR |

Every release also emits SBOM, notices, hashes, tool/model manifests, and signed update artifacts.

## 13. Privacy tests

- deny all app egress during processing;
- distinguish OS/WebView background traffic from app traffic;
- disable updater/model checks and rerun;
- scan logs/crash records for script fragments, recognized words, filenames, absolute paths, keys, and media bytes;
- verify no customer inputs are present in packaged fixtures or telemetry;
- verify sidecar command permissions are allowlisted and arguments are not shell-interpolated.

## 14. Suggested release thresholds to decide

Before implementation, product/engineering must set:

- supported languages and minimum alignment coverage;
- maximum median/P95 word-boundary error;
- zero-tolerance definition for clipped words;
- maximum false-cut rate and acceptable missed-pause rate;
- minimum retained pause and speech guards by boundary type;
- subtitle CPS, line, duration, and gap limits;
- maximum RTF/RSS and minimum hardware;
- installer/model size budget;
- NLE version/rate matrix and timing tolerance;
- whether strict offline installation is promised.
