# Risk register

## 1. Scoring

- Probability: Low / Medium / High.
- Impact: Low / Medium / High / Critical.
- P0: must be resolved before a public release.
- P1: must have mitigation and a passing gate before release candidate.
- P2: track and resolve according to milestone.

## 2. Register

| ID | Priority | Risk | Probability | Impact | Detection / leading indicator | Mitigation | Gate / owner |
|---|---|---|---|---|---|---|---|
| R-01 | P0 | A cut clips the beginning or end of a spoken word | Medium | Critical | Boundary corpus, waveform review, post-render word timing, audible click/phoneme loss | Protect aligned words with pre/post guards; require signal-confirmed silence; conservative no-cut on uncertainty | Audio quality gate; audio lead |
| R-02 | P0 | Local STT timestamps are too inaccurate for safe cuts/subtitles | High | High | ElevenLabs benchmark: boundary error, coverage, WER, RTF | Script-constrained global alignment; model tiers; confidence gating; optional cleaned-audio QA | Model ADR and corpus threshold; ML/audio lead |
| R-03 | P0 | Original case/punctuation/spelling is changed | Medium | High | Exact source-span reconstruction tests | Immutable source script; display text only from character spans; ASR used only for timing | Text fidelity gate; domain lead |
| R-04 | P0 | Retiming drifts after several pause removals | Medium | Critical | Edit-map invariants and long-duration property tests | Integer sample indices; half-open spans; no float accumulation; one mapper for every exporter | Edit-map schema gate; domain lead |
| R-05 | P0 | XML is well-formed but rejected or translated incorrectly by Premiere/Resolve | High | High | DTD validation and real NLE import/reopen reports | Editor-neutral TimelineIR; tested XML profiles; real NLE compatibility matrix; SRT authoritative | NLE release gate; export lead |
| R-06 | P0 | Experimental CapCut draft corrupts user projects | High | Critical | Unknown schema/version, failed reopen, unexpected file mutation | Safe package primary; opt-in; allowlist; new draft only; staging/backup/atomic publish; disposable profile | Separate go/no-go ADR; feature owner |
| R-07 | P0 | Product makes network calls during processing | Medium | High | Egress-blocked acceptance and DNS/TCP audit | Remove cloud SDKs/telemetry; separate updates; fail tests on network attempt | Privacy gate; security owner |
| R-08 | P0 | Bundled FFmpeg violates license policy | Medium | High | Configure/version audit detects GPL/nonfree/libx264 | Pinned reproducible LGPL-compatible audio build; source/build recipe; notices; legal review | Supply-chain release gate; release owner |
| R-09 | P0 | Rights to copy reference code are unclear | Unknown | High | No LICENSE/NOTICE found in archive | Obtain provenance/license decision; otherwise reimplement ideas from behavior/tests without code copying | ADR before code extraction; product/legal owner |
| R-10 | P1 | Greedy/ambiguous matching links a repeated phrase to the wrong occurrence | High | High | Repeated-phrase corpus, low score margin | Global sequence alignment; ambiguity status; no cuts near ambiguity | Alignment coverage gate; domain lead |
| R-11 | P1 | ASR hallucinations on silence create false protected words | Medium | High | Silence/noise fixtures, anomalous low confidence | Combine ASR with signal evidence; confidence thresholds; silence hallucination filtering | Audio integration gate |
| R-12 | P1 | Subtitle blocks are unreadable or out of sync | Medium | High | CPS, line-length, duration, overlap violations; user review | Deterministic global chunker; shared SubtitleCue; no equal division of beat duration | Subtitle validation gate |
| R-13 | P1 | Omitted/inserted/repeated speech is silently misrepresented | High | High | Alignment mismatch report | Explicit policies/statuses; do not invent authoritative timing; warnings | Product ADR and acceptance cases |
| R-14 | P1 | Installer/model size is unacceptable | High | Medium | Target artifact size and update bandwidth | Benchmark model tiers; separate signed quality pack; per-architecture builds | Distribution budget gate |
| R-15 | P1 | Intel Mac or low-end Windows performance is unusable | Medium | High | RTF, peak RSS, thermal/disk benchmarks | Minimum hardware; one STT job; streaming; approved quantization/model | Platform benchmark gate |
| R-16 | P1 | Nested sidecars break signing, notarization, or antivirus reputation | Medium | High | `codesign`, Gatekeeper, Authenticode, SmartScreen/AV clean-room tests | Sign inside-out; stable publisher identity; avoid self-extracting Python onefile | Release pipeline gate |
| R-17 | P1 | Windows paths, UNC, long paths, Unicode, or reserved URI characters break exports | High | Medium | Cross-platform path fixtures and NLE imports | Typed paths; argv arrays; portable URI encoder; traversal rejection | Path test gate |
| R-18 | P1 | Disk fills during decode/STT/render and leaves partial outputs | Medium | High | Admission control and low-disk fault tests | Preflight estimate; streaming; `.partial`; bounded cache; atomic publish | Recovery gate |
| R-19 | P1 | Cancel/crash leaves orphan processes or corrupt job state | Medium | High | Force-kill/restart/process-tree tests | Windows Job Object; macOS process group; durable checkpoints; startup recovery | Recovery matrix |
| R-20 | P1 | App update interrupts a job or mismatches model/schema | Medium | High | Update-during-job and downgrade tests | Idle-only signed updates; schema compatibility; checkpoint; rollback | Updater gate |
| R-21 | P1 | Model download is corrupted or substituted | Low | Critical | Signature/hash mismatch | Signed manifest, SHA-256, atomic install, retain old model until smoke load | Model manager gate |
| R-22 | P2 | Bundled baseline model quality is insufficient for some languages | High | Medium | Per-locale benchmark failures | Define v1 locales; quality pack; warn/fail on unsupported locale | Model/language ADR |
| R-23 | P2 | Breaths, room tone, music, or expressive pauses are removed unnaturally | Medium | High | Human listening panel and signal fixtures | Pause categories; retained pause by boundary type; conservative defaults; preview/report | Audio quality review |
| R-24 | P2 | Leading/trailing silence is trimmed against user expectations | Medium | Medium | Fixture comparison and user feedback | Preserve by default; separate explicit trim option | Product behavior ADR |
| R-25 | P2 | FCPXML/xmeml subtitle titles differ from true caption tracks | High | Medium | Import/round-trip inspection | SRT authoritative; XML titles optional profile; document limitations | Compatibility documentation |
| R-26 | P2 | CapCut schema changes frequently | High | High | Fingerprint mismatch in new CapCut release | Version allowlist; fail closed; safe package unaffected | Experimental adapter maintenance |
| R-27 | P2 | Logs leak script, filenames, or absolute paths | Medium | High | Log content scanner | Structured redacted logs; opt-in crash reports; no media attachment | Privacy gate |
| R-28 | P2 | Reproducibility breaks due to timestamps/archive metadata | Medium | Medium | Byte-different rerun goldens | Stable ordering, normalized archive times, fixed serializers, hashes | Determinism gate |

## 3. Release blockers

No release candidate should be produced until:

1. R-01 through R-09 have closed decisions and passing gates.
2. A licensed ElevenLabs-style corpus proves the chosen STT/pause policy.
3. `edit_map.json` invariants pass on multiple cuts and long files.
4. Premiere and Resolve imports succeed on the supported matrix.
5. Installed builds run with no Python/FFmpeg/model preinstalled and with processing egress blocked.
6. Signing, notarization, Authenticode, notices, hashes, and SBOM are complete.

## 4. CapCut release policy

- `capcut_safe` may ship when its standards-only import workflow is validated.
- Experimental draft generation has an independent feature gate.
- Failure or deferral of the experimental draft must not block the core product or safe package.
- Unknown CapCut version/schema always disables draft generation.

## 5. Risk review cadence

- Review at each ADR closure.
- Review after STT/pause corpus benchmark.
- Review after first NLE import spike.
- Review before adding packaging dependencies.
- Review on every release candidate and every CapCut version allowlist change.
