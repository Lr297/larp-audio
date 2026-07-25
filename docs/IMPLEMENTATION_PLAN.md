# Implementation plan

## 1. Rules of execution

This is a plan, not an implementation. No task below has been started.

Classification follows the LARP theory routing rule:

- **Small Task**: an isolated, usually single-file change of roughly no more than 150 lines, with no new cross-module behavior or integration test requirement.
- **Big Task**: multi-module work, architecture/runtime choice, persistence/schema work, platform packaging, or work requiring integration/acceptance tests.

Global rules:

1. `reference/` remains read-only.
2. Do not migrate Django, Celery, Redis, PostgreSQL, S3/MinIO, cloud AI clients, ChromaDB, or B-roll domain code.
3. Do not add production dependencies until the relevant ADR is approved.
4. Canonical time is integer audio samples with half-open ranges.
5. Every persisted contract is versioned from its first commit.
6. GUI work is deferred until the headless vertical slice passes.
7. Experimental CapCut draft work is independently gated and may be deferred without blocking release.

## 2. Phase 0 - decisions and feasibility gates

### D-01 - Runtime architecture spike

- **Goal:** compare the recommended Tauri/Rust core with a temporary Tauri/Python `onedir` sidecar on one identical headless slice.
- **Input:** one WAV, mocked word timestamps, selected reference alignment/export fixtures.
- **Output:** approved ADR with cold start, bundle-size, RSS, crash/cancel, and signing-complexity measurements.
- **Affected files:** `docs/adr/ADR-001-runtime.md`, `spikes/runtime-rust/**`, `spikes/runtime-python/**` (new).
- **Dependencies:** none; no production dependency may be committed by the spike.
- **Definition of done:** measurements exist for Windows x64, macOS arm64, and macOS x86_64; production runtime is selected.
- **Required tests:** smoke run, forced crash, cancellation, Unicode/space path, empty `PATH`.
- **Risks:** a narrow spike may underestimate model/update and nested-signing complexity.
- **Class:** Big Task.

### D-02 - Local STT and model benchmark

- **Goal:** choose whisper.cpp build, model tier, timestamp mode, and supported languages.
- **Input:** rights-cleared ElevenLabs-style corpus, exact scripts, human word boundaries, candidate model artifacts.
- **Output:** WER, alignment coverage, boundary error, RTF, peak RSS, model size, and a model-selection ADR.
- **Affected files:** `benchmarks/stt/**`, `docs/adr/ADR-002-stt-model.md`, `docs/model-selection.md` (new).
- **Dependencies:** approved corpus/license and benchmark thresholds.
- **Definition of done:** one baseline and optional quality model pass thresholds on all mandatory targets.
- **Required tests:** multilingual, numbers/acronyms, long silence, repeated phrases, omissions/insertions, empty/noisy audio.
- **Risks:** corpus bias or acceptable WER with unacceptable boundary timing.
- **Class:** Big Task.

### D-03 - Audio and alignment policy ADR

- **Goal:** freeze canonical WAV format, pause threshold, retained pause, word guards, breath/leading/trailing policies, and low-confidence behavior.
- **Input:** product goals, D-02 metrics, annotated listening examples.
- **Output:** measurable policy defaults and failure/warning behavior.
- **Affected files:** `docs/adr/ADR-003-audio-policy.md` (new).
- **Dependencies:** D-02 preliminary results.
- **Definition of done:** every ambiguous case has a conservative default and an acceptance metric.
- **Required tests:** ADR examples map to named future fixtures and expected decisions.
- **Risks:** defaults may over-preserve pauses or damage expressive delivery.
- **Class:** Small Task. Any new benchmark is a separate Big Task.

### D-04 - Artifact and persistence contract ADR

- **Goal:** approve `edit_map.json` v1, `TimelineIR`, manifest, job-state model, and JSON-only versus SQLite history.
- **Input:** architecture records and all required output artifacts.
- **Output:** versioned schema definitions, compatibility policy, and migration rules.
- **Affected files:** `docs/adr/ADR-004-artifacts.md`, `schemas/edit-map-v1.schema.json`, `schemas/manifest-v1.schema.json`, `schemas/job-v1.schema.json` (new).
- **Dependencies:** D-03 time/audio policy.
- **Definition of done:** sample-range invariants, hashes/provenance, warnings, and path privacy are explicit.
- **Required tests:** valid/minimal/maximal and invalid schema fixtures; forward unknown-field behavior.
- **Risks:** premature schema lock or missing recovery/provenance fields.
- **Class:** Big Task.

### D-05 - NLE and CapCut feasibility gates

- **Goal:** select Premiere xmeml profile, Resolve FCPXML version/audio-only structure, supported rates/versions, and CapCut draft go/no-go.
- **Input:** minimal cleaned WAV/SRT, official DTD/docs, disposable editor projects and CapCut profiles.
- **Output:** `ADR-005-nle.md`, `ADR-006-capcut.md`, compatibility targets, and redacted draft schema notes.
- **Affected files:** `docs/adr/ADR-005-nle.md`, `docs/adr/ADR-006-capcut.md`, `tests/fixtures/nle/**`, `tests/fixtures/capcut/**` (new).
- **Dependencies:** D-04 TimelineIR draft; access to licensed NLE/CapCut versions.
- **Definition of done:** audio-only imports are proven or rejected; experimental draft scope is explicitly approved/deferred.
- **Required tests:** import/reopen on Windows/macOS, Unicode path, selected rational rates, unknown CapCut schema fail-closed.
- **Risks:** editor translation differs by version; CapCut format may be proprietary/unstable.
- **Class:** Big Task.

## 3. Phase 1 - dependency-free foundation

### F-01 - Repository skeleton and architecture rules

- **Goal:** create the separate core/application/runtime/export/test structure without implementing product behavior.
- **Input:** approved D-01 runtime ADR and proposed layout.
- **Output:** buildable skeleton and forbidden-dependency checks.
- **Affected files:** workspace manifest, `crates/{domain,pipeline,runtime,media,stt,subtitles,export,jobs}/**`, `tests/architecture/**` (new).
- **Dependencies:** D-01.
- **Definition of done:** empty core imports/builds without Django, Celery, boto3, cloud SDKs, FFmpeg, model, or GUI.
- **Required tests:** forbidden import/package gate, no-side-effect import smoke, clean build on mandatory targets.
- **Risks:** skeleton over-engineering or accidental early dependency lock-in.
- **Class:** Big Task.

### F-02 - Integer sample timebase utilities

- **Goal:** implement checked sample arithmetic and explicit sample/ms/frame quantization.
- **Input:** sample indices/rates, rational frame rates, named rounding policy.
- **Output:** deterministic conversion functions with overflow checks.
- **Affected files:** `crates/domain/src/timebase.rs`, `crates/domain/tests/timebase.rs` (new).
- **Dependencies:** D-03 and D-04.
- **Definition of done:** no float accumulation or implicit tie handling; long durations and 1000/1001 rates are supported.
- **Required tests:** 44.1/48/96 kHz, 24/25/30/23.976/29.97/59.94, half-frame ties, overflow, monotonic repair.
- **Risks:** inconsistent start/end rounding can create overlap or truncate the tail.
- **Class:** Small Task.

### F-03 - Core immutable contracts

- **Goal:** define `AudioInfo`, `ASRWord`, `ScriptToken`, `TokenAlignment`, `EditMap`, `TimedToken`, `SubtitleCue`, and `TimelineIR`.
- **Input:** D-04 schemas and F-02 time types.
- **Output:** validated immutable records with stable serialization boundaries.
- **Affected files:** `crates/domain/src/contracts/*.rs`, `crates/domain/tests/contracts/**` (new).
- **Dependencies:** F-02 and D-04.
- **Definition of done:** invalid ranges, missing provenance, overlaps, and illegal statuses cannot enter the pipeline.
- **Required tests:** valid/invalid constructors, Unicode text, empty/long inputs, schema round-trip.
- **Risks:** coupling editor-specific details into the domain model.
- **Class:** Big Task.

### F-04 - Portable path and resource resolver

- **Goal:** resolve installed sidecars/models without `PATH` and provide safe portable relative paths.
- **Input:** target/architecture, bundle layout, user paths.
- **Output:** validated absolute resource paths and package-relative path values.
- **Affected files:** `crates/runtime/src/resources.rs`, `crates/runtime/tests/resources.rs` (new).
- **Dependencies:** D-01 bundle-layout decision.
- **Definition of done:** relocated app works with empty `PATH`; missing/wrong-arch resources return actionable errors.
- **Required tests:** macOS bundle, Windows install, spaces, Cyrillic, emoji, read-only resources, symlink/reparse edge cases.
- **Risks:** platform layouts and installer behavior diverge.
- **Class:** Small Task.

### F-05 - Process supervisor and cancellation

- **Goal:** run sidecars with typed progress and guaranteed process-tree termination.
- **Input:** executable path, argv array, environment allowlist, cancellation token.
- **Output:** typed events, exit result, sanitized error, bounded shutdown.
- **Affected files:** `crates/runtime/src/process/{mod,macos,windows}.rs`, `crates/runtime/tests/process/**` (new).
- **Dependencies:** F-04.
- **Definition of done:** cancel/crash leaves no child or grandchild process and no pipe deadlock.
- **Required tests:** Windows Job Object, macOS process group, hung stdout/stderr, malformed progress, force-kill race.
- **Risks:** process-group semantics, deadlocks, and cancellation races.
- **Class:** Big Task.

### F-06 - Durable job workspace and state machine

- **Goal:** implement checkpoints, `.partial` artifacts, state transitions, recovery scan, and atomic publication.
- **Input:** job request, app-data/cache/output locations, D-04 job schema.
- **Output:** versioned `job.json`, stage directories, recovery classification, published artifact directory.
- **Affected files:** `crates/jobs/src/{state,workspace,recovery,publish}.rs`, `crates/jobs/tests/**` (new).
- **Dependencies:** F-03, F-04, F-05.
- **Definition of done:** force-kill at every stage never exposes a partial final artifact; restart reports resumable/cleanable/corrupt.
- **Required tests:** low disk, unwritable output, stale job, schema migration, cancellation, concurrent output collision.
- **Risks:** recovery schema churn and accidental deletion of user files.
- **Class:** Big Task.

## 4. Phase 2 - audio, STT, alignment, and edit map

### A-01 - Bundled ffprobe adapter

- **Goal:** obtain trusted input metadata from the resolved ffprobe binary.
- **Input:** local audio path.
- **Output:** validated `AudioInfo` and diagnostic report.
- **Affected files:** `crates/media/src/probe.rs`, `crates/media/tests/probe.rs` (new).
- **Dependencies:** F-03, F-04, F-05.
- **Definition of done:** supported formats return sample rate/channels/duration; malformed values fail safely.
- **Required tests:** WAV/MP3/M4A fixtures, corrupt/truncated/zero-length input, Unicode/UNC paths.
- **Risks:** container metadata duration may differ from decoded sample count.
- **Class:** Small Task.

### A-02 - Canonical streaming decode

- **Goal:** stream supported inputs to the canonical PCM analysis format without loading the whole file.
- **Input:** probed audio and D-03 canonical format.
- **Output:** PCM stream/cache metadata with exact decoded sample count.
- **Affected files:** `crates/media/src/decode.rs`, `crates/media/tests/decode.rs`, `tests/fixtures/audio/**` (new).
- **Dependencies:** A-01 and F-05.
- **Definition of done:** decoded count is stable and cancellation/low-disk behavior is bounded.
- **Required tests:** sample rates/channels, long stream, corrupt packet, cancel, disk pressure, empty `PATH`.
- **Risks:** resampling delay and codec-specific priming can shift boundaries.
- **Class:** Big Task.

### A-03 - Local whisper wrapper and adapter

- **Goal:** expose stable word-level local STT independent of upstream CLI text format.
- **Input:** canonical audio, verified model, language/config, cancellation token.
- **Output:** `TranscriptionResult` with source sample ranges, confidence/provenance, progress.
- **Affected files:** `tools/whisper-wrapper/**`, `crates/stt/src/{adapter,schema}.rs`, `crates/stt/tests/**` (new).
- **Dependencies:** D-02, F-05, A-02, future packaged whisper binary.
- **Definition of done:** same machine-readable schema and error codes on all mandatory targets; no network access.
- **Required tests:** silence/noise/long file, language hints, corrupt model, cancel/crash, timestamp bounds.
- **Risks:** upstream timestamp quality or CLI/API instability.
- **Class:** Big Task.

### A-04 - Unicode script tokenizer

- **Goal:** tokenize the exact original script while retaining every character span and punctuation relationship.
- **Input:** immutable script and locale.
- **Output:** ordered `ScriptToken` records plus whitespace/paragraph metadata.
- **Affected files:** `crates/domain/src/tokenize.rs`, `crates/domain/tests/tokenize.rs` (new).
- **Dependencies:** F-03 and supported-locale decision from D-02.
- **Definition of done:** source slices reconstruct exact graphemes/case/punctuation; matching normalization is separate.
- **Required tests:** Cyrillic, diacritics, mixed scripts, CJK/RTL policy, quotes/dashes, NBSP, numbers/URLs/emails.
- **Risks:** locale-specific token boundaries and Unicode normalization surprises.
- **Class:** Small Task.

### A-05 - Global script-to-ASR aligner

- **Goal:** map script tokens to ASR words with explicit mismatch and ambiguity status.
- **Input:** `ScriptToken[]`, `ASRWord[]`, locale/config.
- **Output:** `AlignmentResult`, coverage/confidence summary, protected speech intervals.
- **Affected files:** `crates/domain/src/alignment/{mod,normalize,score,dp}.rs`, `crates/domain/tests/alignment/**` (new).
- **Dependencies:** A-03, A-04, F-02/F-03.
- **Definition of done:** exact/fuzzy/many-to-many/insertion/omission/repetition/ambiguity are distinguished; repeated phrases do not silently misbind.
- **Required tests:** migrated reference fixtures plus Cyrillic, numbers, long drift, duplicated take, malformed timestamps, low confidence.
- **Risks:** computational cost and false confidence on repeated text.
- **Class:** Big Task.

### A-06 - Candidate silence detector

- **Goal:** identify possible long pauses using signal evidence and inter-word gaps without deciding cuts.
- **Input:** canonical PCM stream, ASR words, detection config.
- **Output:** candidate spans with duration, energy/silence metrics, boundary context, confidence.
- **Affected files:** `crates/domain/src/pause/detect.rs`, `crates/domain/tests/pause_detect.rs` (new).
- **Dependencies:** A-02, A-03, D-03.
- **Definition of done:** threshold behavior is sample-exact; breaths/room tone/music yield explainable metrics.
- **Required tests:** exact thresholds, low-level noise, breathing, long silence, all silence, overlapping word gaps.
- **Risks:** simple energy thresholds may fail on noisy or music-backed audio.
- **Class:** Big Task.

### A-07 - Conservative pause cut planner

- **Goal:** turn candidates into safe retained/removed spans without intersecting protected speech.
- **Input:** A-06 candidates, A-05 protected intervals/confidence, D-03 pause policy.
- **Output:** validated edit operations with no-cut warnings.
- **Affected files:** `crates/domain/src/pause/plan.rs`, `crates/domain/tests/pause_plan.rs` (new).
- **Dependencies:** A-05, A-06, F-03.
- **Definition of done:** only pause middles are removed; natural pause and guards remain; uncertain cases are preserved.
- **Required tests:** touching/overlapping guards, low confidence, adjacent candidates, leading/trailing policy, one-sample boundaries.
- **Risks:** over-conservative output leaves long pauses; aggressive defaults clip speech.
- **Class:** Big Task.

### A-08 - Edit map builder and mapper

- **Goal:** construct sample-exact kept/removed spans and map source words/ranges to cleaned coordinates.
- **Input:** source sample count and A-07 edit operations.
- **Output:** validated `EditMap` and source-to-output mapping API.
- **Affected files:** `crates/domain/src/edit_map/{build,map,validate}.rs`, `crates/domain/tests/edit_map/**` (new).
- **Dependencies:** F-02/F-03, A-07, D-04.
- **Definition of done:** partition/gapless/length/monotonic invariants pass for arbitrary valid cuts.
- **Required tests:** property/fuzz cases, multiple cuts, edge cuts, removed-time status, long duration, overflow.
- **Risks:** off-by-one errors propagate into every output.
- **Class:** Big Task.

### A-09 - Cleaned WAV renderer

- **Goal:** render `cleaned_audio.wav` from the edit map into staging with safe splice treatment.
- **Input:** source audio, canonical output format, validated edit map.
- **Output:** WAV and `RenderReport` with actual sample count/hash/tool version.
- **Affected files:** `crates/media/src/render.rs`, `crates/media/tests/render.rs` (new).
- **Dependencies:** A-02, A-08, F-05/F-06.
- **Definition of done:** actual sample count matches edit map; source/final files are never overwritten in place.
- **Required tests:** no/multiple cuts, click-prone boundaries, channels/rates, cancel, low disk, corrupt sidecar output.
- **Risks:** splice clicks, resampling delay, or FFmpeg filter rounding.
- **Class:** Big Task.

### A-10 - Post-render audio validator

- **Goal:** fail publication when WAV format, duration, hash, or splice invariants disagree.
- **Input:** rendered WAV, render report, edit map, expected audio policy.
- **Output:** validation report with stable warning/error codes.
- **Affected files:** `crates/media/src/validate.rs`, `crates/media/tests/validate.rs` (new).
- **Dependencies:** A-01, A-08, A-09.
- **Definition of done:** sample-count or format mismatch blocks final publication.
- **Required tests:** truncated WAV, wrong sample rate/channels, off-by-one duration, tampered output.
- **Risks:** validation may miss perceptual word clipping without corpus annotations.
- **Class:** Small Task.

## 5. Phase 3 - subtitles

### S-01 - Timed script token reducer

- **Goal:** apply edit-map timings and mismatch policy to produce canonical timed original-script tokens.
- **Input:** alignment result, edit map, D-03 mismatch policy.
- **Output:** `TimedToken[]` plus omission/insertion/repetition report.
- **Affected files:** `crates/subtitles/src/timed_tokens.rs`, `crates/subtitles/tests/timed_tokens.rs` (new).
- **Dependencies:** A-05, A-08, F-03.
- **Definition of done:** display text comes only from source spans; fabricated timing is labeled or excluded.
- **Required tests:** omission, insertion, repeat, ambiguity, word crossing removed span, punctuation-only tokens.
- **Risks:** product expectations for audible repeats may conflict with script-authoritative text.
- **Class:** Small Task.

### S-02 - Deterministic readability-aware chunker

- **Goal:** build readable subtitle cues from timed original tokens using global boundary optimization.
- **Input:** timed tokens, source paragraph/punctuation/pause metadata, `SubtitleConfig`.
- **Output:** validated `SubtitleCue[]` with line layout and warning codes.
- **Affected files:** `crates/subtitles/src/chunk/{mod,cost,layout}.rs`, `crates/subtitles/tests/chunk/**` (new).
- **Dependencies:** S-01, D-03 subtitle limits.
- **Definition of done:** hard constraints are met or explicitly warned; results are deterministic and locale-aware.
- **Required tests:** reference chunk cases, CPS/duration/line limits, orphan rebalance, quotes/dashes, CJK/RTL policy, long token.
- **Risks:** too many constraints create unnatural or infeasible cue layouts.
- **Class:** Big Task.

### S-03 - SRT serializer and validator

- **Goal:** produce authoritative UTF-8 `subtitles.srt` from canonical cues.
- **Input:** validated `SubtitleCue[]` and audio duration.
- **Output:** SRT text/file and validation report.
- **Affected files:** `crates/subtitles/src/srt.rs`, `crates/subtitles/tests/srt.rs` (new).
- **Dependencies:** S-02 and F-02.
- **Definition of done:** sequential indices, comma milliseconds, monotonic nonoverlap, final cue within WAV.
- **Required tests:** zero/long hour values, Cyrillic/emoji, `-->` in text, rounding ties, empty cues.
- **Risks:** millisecond quantization may create zero-duration or touching cues without repair.
- **Class:** Small Task.

## 6. Phase 4 - exports and packages

### E-01 - `edit_map.json` serializer

- **Goal:** serialize the validated edit map, remapped words, policy, hashes, versions, and warnings.
- **Input:** D-04 schema, A-08 edit map, A-10 report, alignment/model/tool provenance.
- **Output:** deterministic `edit_map.json`.
- **Affected files:** `crates/export/src/edit_map_json.rs`, `crates/export/tests/edit_map_json.rs` (new).
- **Dependencies:** D-04, A-08, A-10, S-01.
- **Definition of done:** schema-valid, stable ordering, no absolute paths, source/output hashes match.
- **Required tests:** minimal/full payload, Unicode, unknown status, deterministic bytes, schema rejection.
- **Risks:** artifact grows large if every token/word duplicates excessive metadata.
- **Class:** Small Task.

### E-02 - TimelineIR builder

- **Goal:** create editor-neutral audio-first timeline data.
- **Input:** cleaned WAV metadata, rational rate/profile, canonical subtitle cues.
- **Output:** validated `TimelineIR`.
- **Affected files:** `crates/export/src/timeline.rs`, `crates/export/tests/timeline.rs` (new).
- **Dependencies:** F-03, A-10, S-02, D-05.
- **Definition of done:** missing/nonmonotonic/out-of-range timing is rejected; no B-roll/Django fields exist.
- **Required tests:** audio-only, no subtitles, Unicode project name, supported/unsupported rates, long duration.
- **Risks:** editor-specific compromises leak into the common model.
- **Class:** Small Task.

### E-03 - Cross-platform XML URI serializer

- **Goal:** generate editor-safe URIs/pathurl values without traversal or host-path leakage.
- **Input:** package-relative path or explicitly allowed local absolute path.
- **Output:** normalized encoded URI/path value.
- **Affected files:** `crates/export/src/path_uri.rs`, `crates/export/tests/path_uri.rs` (new).
- **Dependencies:** F-04 and D-05 path policy.
- **Definition of done:** POSIX, Windows drive, UNC, Unicode, spaces, `#`, `%` are covered; portable mode rejects absolute/traversal paths.
- **Required tests:** golden paths for both OS families and editor import samples.
- **Risks:** Premiere and Resolve may interpret relative references differently.
- **Class:** Small Task.

### E-04 - Premiere xmeml exporter

- **Goal:** generate `premiere.xml` containing the final WAV and approved optional title profile.
- **Input:** TimelineIR and E-03 media URI.
- **Output:** FCP7 XML/xmeml with actual audio metadata and explicit rate policy.
- **Affected files:** `crates/export/src/premiere_xmeml.rs`, `crates/export/tests/premiere_xmeml.rs`, `tests/golden/export/premiere/**` (new).
- **Dependencies:** E-02, E-03, D-05.
- **Definition of done:** real Premiere imports online media, exact tail, intended rate, and no silent 2.5-second fallback.
- **Required tests:** XML syntax, Unicode/escaping, rational rates, mono/stereo, missing/overlap rejection, Windows/macOS import/reopen.
- **Risks:** legacy Text/title translation and relative path dialect vary by Premiere version.
- **Class:** Big Task.

### E-05 - Resolve FCPXML exporter

- **Goal:** generate DTD-valid, tested `resolve.fcpxml` around one cleaned WAV asset.
- **Input:** TimelineIR and E-03 media URI.
- **Output:** selected FCPXML version document.
- **Affected files:** `crates/export/src/resolve_fcpxml.rs`, `crates/export/tests/resolve_fcpxml.rs`, `tests/golden/export/resolve/**` (new).
- **Dependencies:** E-02, E-03, D-05.
- **Definition of done:** DTD passes and Resolve Windows/macOS imports online audio with correct duration/rate.
- **Required tests:** DTD, syntax, Unicode, rates, tail, relative relink, real import/reopen.
- **Risks:** DTD-valid data may still be rejected; FCPXML behavior differs from Resolve.
- **Class:** Big Task.

### E-06 - Deterministic artifact bundle and manifest

- **Goal:** assemble exact required filenames, manifest, checksums, and optional ZIP reproducibly.
- **Input:** cleaned WAV, SRT, XMLs, edit map, tool/model/job provenance.
- **Output:** atomically published output directory and deterministic archive profile.
- **Affected files:** `crates/export/src/{manifest,package}.rs`, `crates/export/tests/package.rs` (new).
- **Dependencies:** F-06, E-01, E-04, E-05, S-03.
- **Definition of done:** no absolute/traversal paths; reruns are byte-identical except explicitly normalized exclusions.
- **Required tests:** missing artifact, tampered hash, duplicate filename, archive timestamp normalization, cancellation before publish.
- **Risks:** archive metadata breaks reproducibility or large WAV doubles disk use.
- **Class:** Big Task.

### E-07 - Safe CapCut package

- **Goal:** create a non-mutating CapCut import package from standards-based artifacts.
- **Input:** cleaned WAV, SRT, edit map, manifest.
- **Output:** `capcut_safe/` with checksums and concise import instructions.
- **Affected files:** `crates/export/src/capcut_safe.rs`, `crates/export/tests/capcut_safe.rs`, `docs/capcut-safe-import.md` (new).
- **Dependencies:** E-06 and S-03.
- **Definition of done:** exporter never reads/writes CapCut draft directories; package imports manually on CapCut Desktop Windows/macOS.
- **Required tests:** fixed contents, UTF-8 Cyrillic SRT, no absolute paths, manual import checklist.
- **Risks:** users may expect a one-click project instead of an import package.
- **Class:** Small Task.

### E-08 - Experimental new CapCut draft adapter

- **Goal:** create a new draft only for explicitly allowlisted CapCut versions after D-05 approval.
- **Input:** safe package, platform/version fingerprint, disposable target library.
- **Output:** a new staged and atomically published draft copy.
- **Affected files:** `crates/export/src/capcut_draft/{mod,macos,windows}.rs`, `tests/integration/capcut_draft/**` (new).
- **Dependencies:** D-05 go decision and E-07; otherwise deferred.
- **Definition of done:** unknown versions fail closed; no existing draft is mutated; reopen verification passes.
- **Required tests:** disposable profile, backup/restore, interruption, schema mismatch, path relocation, reopen.
- **Risks:** P0 data corruption, proprietary/schema churn, legal/support cost.
- **Class:** Big Task.

## 7. Phase 5 - headless integration and distribution

### P-01 - Headless end-to-end application service

- **Goal:** connect fake then real adapters into one cancelable local pipeline before GUI work.
- **Input:** audio path, original script, config, output directory.
- **Output:** complete validated artifact set and job report.
- **Affected files:** `crates/pipeline/src/{service,stages}.rs`, `crates/pipeline/tests/e2e.rs` (new).
- **Dependencies:** F-06, A-03 through A-10, S-03, E-06/E-07.
- **Definition of done:** one command/API completes offline and every stage is checkpointed and deterministic.
- **Required tests:** golden E2E, no-cut/multi-cut, cancel each stage, force-kill/restart, corrupt input/model/tool.
- **Risks:** orchestration may duplicate domain logic or expose partially valid artifacts.
- **Class:** Big Task.

### P-02 - Signed model pack manager

- **Goal:** discover, verify, atomically install, select, and roll back bundled/downloaded models.
- **Input:** signed manifest, model artifact, app/model compatibility rules.
- **Output:** verified active model path and provenance.
- **Affected files:** `crates/runtime/src/models/**`, `distribution/models/manifest.json`, `distribution/models/README.md` (new).
- **Dependencies:** D-02, F-04/F-06, signing-key policy.
- **Definition of done:** corrupt/interrupted update cannot replace the last working model; fully offline mode works.
- **Required tests:** wrong hash/signature, low disk, network loss, rollback, key rotation, model/app mismatch.
- **Risks:** large downloads, signing-key lifecycle, model license/provenance.
- **Class:** Big Task.

### P-03 - Reproducible FFmpeg and whisper sidecars

- **Goal:** build pinned, signed-ready binaries for every supported target with machine-readable manifests.
- **Input:** approved upstream commits, FFmpeg flags, whisper wrapper, target matrix.
- **Output:** per-target binaries, hashes, source/build recipes, notices.
- **Affected files:** `distribution/{ffmpeg,whisper}/**`, release CI configuration (new).
- **Dependencies:** D-02, D-03, license ADR, A-03 adapter schema.
- **Definition of done:** FFmpeg audit shows no GPL/nonfree; all binaries pass adapter contract tests.
- **Required tests:** version/config audit, decode/probe/STT fixtures, cancel/crash, architecture mismatch.
- **Risks:** build drift, codec patent exposure, nested dynamic libraries.
- **Class:** Big Task.

### P-04 - macOS release pipeline

- **Goal:** produce separate arm64/x86_64 signed and notarized DMGs plus signed update artifacts.
- **Input:** application, sidecars, baseline model policy, Developer ID credentials.
- **Output:** DMGs, signatures, notarization tickets, SBOM/notices/hashes.
- **Affected files:** macOS Tauri/release configuration and CI workflows (new).
- **Dependencies:** P-01, P-02, P-03, signing account.
- **Definition of done:** clean quarantined Macs run a full offline job without bypass instructions.
- **Required tests:** nested `codesign`, `spctl`, staple validation, install/relocate/uninstall, cancel/recovery.
- **Risks:** entitlements/Hardened Runtime, Intel performance, notarization failures.
- **Class:** Big Task.

### P-05 - Windows x64 release pipeline

- **Goal:** produce signed, timestamped per-user offline installer and update artifacts.
- **Input:** application, sidecars, baseline model/WebView2 policy, signing identity.
- **Output:** installer, signatures, SBOM/notices/hashes.
- **Affected files:** Windows Tauri/bundle configuration and CI workflows (new).
- **Dependencies:** P-01, P-02, P-03, code-signing account.
- **Definition of done:** clean VM installs without preinstalled Python/FFmpeg/model and runs offline without elevation if promised.
- **Required tests:** Authenticode, install/uninstall/update, empty `PATH`, AV/SmartScreen observation, long/UNC paths, cancel/recovery.
- **Risks:** SmartScreen reputation, offline installer size, WebView2 behavior.
- **Class:** Big Task.

### P-06 - Desktop shell integration and GUI

- **Goal:** expose the proven headless service through file selection, script input, policy selection, progress, cancellation, warnings, and output reveal.
- **Input:** P-01 typed service/events and approved UX requirements.
- **Output:** cross-platform desktop interaction; no processing logic in UI.
- **Affected files:** `apps/desktop/**` (new).
- **Dependencies:** P-01 and stable contracts; explicitly deferred until headless acceptance.
- **Definition of done:** UI can start/cancel/recover jobs and present warnings/artifacts without direct sidecar access.
- **Required tests:** UI state transitions, accessibility, long paths, cancel/restart, error localization, no processing network calls.
- **Risks:** GUI work may hide unstable core contracts or expand scope.
- **Class:** Big Task.

### P-07 - Signed app/model updater and rollback

- **Goal:** separate app and model update channels and prevent updates during active jobs.
- **Input:** signed release/model manifests, compatibility rules, job state.
- **Output:** staged verified update, rollback path, audit event.
- **Affected files:** `crates/runtime/src/update/**`, desktop updater integration, release metadata (new).
- **Dependencies:** P-02, P-04/P-05, F-06.
- **Definition of done:** bad signature/network interruption never replaces working app/model; active job is never interrupted.
- **Required tests:** idle/active job, bad signature, downgrade, network loss, forced exit, rollback, app/model mismatch.
- **Risks:** update security and schema compatibility.
- **Class:** Big Task.

### P-08 - SBOM, notices, and license CI gate

- **Goal:** fail releases with unknown license/hash/provenance or forbidden FFmpeg configuration.
- **Input:** dependency locks, binary/model manifests, build recipes.
- **Output:** SPDX/CycloneDX SBOM, notices, policy report.
- **Affected files:** `distribution/compliance/**`, `THIRD_PARTY_NOTICES.md`, compliance CI workflow (new).
- **Dependencies:** P-03 and reference-code rights decision.
- **Definition of done:** every shipped component has source/version/hash/license; gate is fail-closed.
- **Required tests:** intentionally missing license/hash, GPL flag, altered binary, stale source recipe.
- **Risks:** transitive native dependencies may be difficult to inventory.
- **Class:** Small Task.

## 8. Phase 6 - release qualification

### Q-01 - Versioned corpus and golden harness

- **Goal:** make audio/alignment/subtitle/export regressions reviewable and deterministic.
- **Input:** licensed corpus, synthetic fixtures, approved policies/schemas.
- **Output:** fixture manifest, generators, goldens, metric reports, controlled update workflow.
- **Affected files:** `tests/fixtures/**`, `tests/golden/**`, `benchmarks/**`, fixture licenses/manifests (new).
- **Dependencies:** D-02/D-04 and implementations under test.
- **Definition of done:** each fixture has hashes/provenance/expected behavior; golden changes require reviewed metrics.
- **Required tests:** fixture integrity, deterministic regeneration, no customer data, coverage report.
- **Risks:** corpus licensing and inadequate voice/language diversity.
- **Class:** Big Task.

### Q-02 - Offline/privacy acceptance suite

- **Goal:** prove local processing and log/content privacy on packaged builds.
- **Input:** release installer and representative full job.
- **Output:** egress-attempt report and sanitized-log report.
- **Affected files:** `tests/privacy/**`, `docs/privacy-verification.md` (new).
- **Dependencies:** packaged P-04/P-05 builds.
- **Definition of done:** full processing succeeds with egress blocked and updater disabled; no sensitive content appears in logs.
- **Required tests:** DNS/TCP audit, log scanning, crash report opt-in, sidecar allowlist, argv injection attempts.
- **Risks:** OS/WebView traffic may be confused with application traffic.
- **Class:** Small Task.

### Q-03 - Cross-platform recovery qualification

- **Goal:** verify install, cancel, force-kill, restart, low disk, and cleanup on clean machines.
- **Input:** release candidates and long-running fixture jobs.
- **Output:** per-platform recovery matrix and blocker list.
- **Affected files:** `tests/release/recovery/**`, `docs/release-qualification/recovery.md` (new).
- **Dependencies:** F-06, P-04/P-05.
- **Definition of done:** all mandatory targets recover without corrupting final/user files or leaving processes.
- **Required tests:** kill at every stage, read-only input, unwritable output, stale partials, power-loss simulation, relocation.
- **Risks:** VM behavior may not represent real storage/performance conditions.
- **Class:** Big Task.

### Q-04 - Premiere/Resolve/CapCut acceptance matrix

- **Goal:** qualify every promised editor/version/platform profile using real imports.
- **Input:** golden artifact packages and supported application versions.
- **Output:** signed compatibility matrix, translation warnings, known limitations.
- **Affected files:** `tests/integration/nle/**`, `tests/integration/capcut/**`, `docs/NLE_COMPATIBILITY.md` (new).
- **Dependencies:** E-04/E-05/E-07 and optionally E-08.
- **Definition of done:** media online, rate/tail correct, SRT text/timing correct, reopen succeeds; experimental draft only on allowlist.
- **Required tests:** Windows/macOS, approved rates, Unicode/reserved paths, mono/stereo, safe CapCut import, disposable draft reopen.
- **Risks:** licensed GUI applications limit automation and version coverage.
- **Class:** Big Task.

## 9. Recommended milestone order

```text
M0: D-01..D-05 decisions
M1: F-01..F-06 foundation
M2: A-01..A-10 + Q-01 audio/alignment quality
M3: S-01..S-03 subtitles
M4: E-01..E-07 standards-based exports
M5: P-01 headless vertical slice
M6: P-02..P-05 + P-08 signed self-contained packages
M7: Q-02..Q-04 release qualification
M8: P-06 GUI
M9: P-07 updater and optional E-08 experimental CapCut draft
```

Parallelism after decisions:

- F-02/F-03 can proceed alongside F-04/F-05.
- A-04 tokenizer can proceed alongside A-01/A-02 media adapters.
- SRT work can start once `SubtitleCue` is stable, while NLE exporters use the same TimelineIR.
- macOS and Windows release pipelines can proceed in parallel after pinned sidecars exist.
- Experimental CapCut draft work stays isolated from the critical path.

## 10. First implementation boundary

The first safe implementation increment should end after a headless fake-adapter vertical slice:

```text
input request
  -> validated sample-based contracts
  -> fake word timestamps
  -> fake safe edit map
  -> real subtitle/edit-map serializers
  -> deterministic staged package
```

Only after this slice proves dependency isolation, schemas, atomic publication, and cancellation should the project add actual FFmpeg/whisper production dependencies.
