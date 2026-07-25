# Extraction report

## 1. Scope and provenance

This report covers the read-only reference materials prepared from the files supplied by the user:

- `reference/ivm_ai_backend/` - extracted from `ivm_ai_backend-main.zip`;
- `reference/LARP_theory.pdf` - copied from the supplied LARP theory PDF.

Input hashes:

| Input | SHA-256 |
|---|---|
| `ivm_ai_backend-main.zip` | `005481525c687bb398d52e927428022e385e5c0c6b4ceb5374840840f93a8e30` |
| `reference/LARP_theory.pdf` | `c98e98b7abf871346d1f673fc1d1d362aa673e9771698f70484d980ae620f3b5` |

The archive contains 245 files, including 207 Python files and about 19,201 Python lines. The PDF has 15 pages. It was rendered and visually inspected; its role in this work is methodological, not a source of audio/subtitle algorithms.

No existing source file was modified. No product implementation, GUI, or production dependency was added.

## 2. Executive conclusion

The reference repository is a multi-user SaaS backend for B-roll matching and timeline export. It is not a reusable desktop foundation. A few algorithms and test fixtures are valuable, but the target product requires a new local, audio-first pipeline.

The extraction boundary is:

```text
Reuse concepts/tests from selected engine modules
                    |
                    v
New standalone local core
                    |
        no Django / Celery / S3 / cloud AI
```

The most important findings are:

1. The current STT adapter calls the OpenAI Audio Transcriptions API, not a local model (`engine/processing/transcribe.py:26,57-93`).
2. In the primary target scenario - audio plus a caller-supplied original script - transcription is skipped, so word timestamps are not obtained (`apps/projects/tasks.py:360-381,489-503`).
3. The existing alignment is beat-level, ASCII-only, greedy, and frame-based (`engine/alignment/align.py:35-53,232-298`). Cyrillic produces no usable tokens.
4. The repository contains no long-pause detector, speech-boundary guard, edit map, source-to-cleaned time transform, SRT renderer, or CapCut exporter.
5. The existing cleaner transcodes video to H.264/AAC and strips metadata; it does not shorten pauses (`engine/cleaning/cleaner.py:109-173`).
6. XML exporters are pure Python and useful as references, but they build stock-video timelines and divide subtitle blocks evenly across beat duration rather than use word timestamps (`engine/export/fcpxml.py:255-285`; `engine/export/premiere_xml.py:206-231`).
7. The server composition mixes Django, Celery, Redis, PostgreSQL, S3/MinIO, cloud AI clients, and ChromaDB (`requirements.txt:1-20`; `docker-compose.yml:1-91`). None of that should be transferred wholesale.

## 3. Requirement coverage in the reference repository

| Target capability | Current state | Extraction decision |
|---|---|---|
| Detect long pauses | Absent | New implementation |
| Shorten pauses, preserve natural short pauses | Absent | New pause policy and cut planner |
| Never clip spoken word edges | Absent | New protected speech intervals and guards |
| Produce `cleaned_audio.wav` | Absent | New canonical PCM/WAV renderer |
| Word-level timestamps | Cloud API adapter exists | Replace with local STT adapter; reuse DTO idea only |
| Align audio to original script | Partial beat-level greedy matcher | Rewrite as Unicode global token alignment |
| Preserve original case/punctuation/spelling | Requested only through an LLM prompt | Enforce with character spans into immutable source text |
| Readable subtitle blocks | Simple deterministic 2-8-word chunker | Adapt ideas, rewrite around timing/CPS/line constraints |
| Retiming after pause deletion | Absent | New sample-accurate edit map and mapper |
| `subtitles.srt` | Absent | New serializer/validator |
| `premiere.xml` | Video-oriented xmeml exists | Rewrite against audio-first Timeline IR |
| `resolve.fcpxml` | Video-oriented FCPXML exists | Rewrite and validate against DTD/Resolve |
| `edit_map.json` | Absent | Define versioned schema first |
| Safe CapCut package | Absent | Standards-only WAV + SRT + manifest package |
| Experimental CapCut draft | Absent | Deferred, opt-in, version-gated adapter |
| Fully local processing | Not satisfied | New architecture; remove all cloud paths |
| No user-installed runtime/tools/models | Not satisfied | Bundle and sign all runtime components |

## 4. Reuse classification

### 4.1 Reuse as test specifications and design patterns

- Alignment regression cases for compounds, percentages, hyphens, fuzzy suffix drift, monotonic resync, and internal misses: `engine/alignment/test_align.py:76-285`.
- Subtitle chunking cases for max/min words, conjunctions, punctuation, and orphan tails: `engine/processing/test_script.py:123-181`.
- XML escaping, deterministic IDs, asset deduplication, relative bundle layout, and source-window clamping: `engine/export/fcpxml.py`, `engine/export/premiere_xml.py`, `engine/export/timing.py`.
- Dependency-injection style used for LLM callables: `engine/processing/script.py:10-12,53-66`. The local product should use the same principle for STT, media tools, storage, progress, and cancellation.
- Progress-callback concept from `engine/cleaning/cleaner.py:109-173`, after replacing bare executable names with resolved bundled paths.

### 4.2 Extract only after adaptation

- Monotonic forward alignment and subtoken-to-source-word provenance from `engine/alignment/align.py`.
- Punctuation/conjunction boundaries from `_stage2_chunk_subtitles()` (`engine/processing/script.py:157-213`) as soft signals, not complete readability rules.
- XML construction patterns, not their current B-roll input contract.
- The `Job` fields `status`, `stage`, `progress`, `result`, and `error` as inspiration for a local job state machine (`apps/jobs/models.py:6-23`), not the Django model.

### 4.3 Rewrite

- Local transcription and model lifecycle.
- Unicode script tokenization and global script-to-ASR alignment.
- Pause detection, conservative cut planning, audio rendering, and timestamp remapping.
- Subtitle cue generation and SRT output.
- Audio-first Premiere xmeml and Resolve FCPXML exporters.
- Local orchestration, cancellation, recovery, artifact manifests, and atomic publication.
- Cross-platform path/URI handling.

### 4.4 Drop from target scope

- `apps/**`, Django models/migrations/views/serializers/admin/auth.
- Celery, Redis, beat schedules, and broker/result semantics.
- PostgreSQL as a required service.
- S3/MinIO/boto3 and presigned URLs.
- Anthropic, OpenAI, Gemini, embeddings, ChromaDB, B-roll matching, brands, winners, and corrections.
- Gunicorn, WSGI/ASGI, and the Docker Compose service topology.

## 5. Detailed findings

### 5.1 Transcription and alignment

`transcribe_audio_timed()` is a thin cloud adapter that returns only recognized text and `{word,start,end}` records. It does not persist language, confidence, model provenance, or timing quality (`engine/processing/transcribe.py:57-93`). Tests mock the API and do not use real audio (`engine/processing/test_transcribe.py:7-81`).

`align_segments()` tokenizes with `[a-z0-9]+`, searches forward with a 20-subtoken lookahead, allows three skips, and uses `difflib.SequenceMatcher` at ratio 0.84 for words of length at least five (`engine/alignment/align.py:35-135`). It returns frame ranges for whole beats. Internal misses are assigned fabricated intervals between neighbors (`engine/alignment/align.py:169-229`), which is unsuitable for authoritative subtitle timing.

The new aligner must operate on Unicode script tokens that retain exact character spans and many-to-many links to ASR words. Each result must be marked `exact`, `fuzzy`, `omitted`, `inserted`, `repeated`, `ambiguous`, or `interpolated`, with confidence and provenance.

### 5.2 Original text fidelity

The current beat segmentation asks a remote LLM to copy text verbatim (`engine/processing/script.py:107-119`) but validates only that the reply is a JSON list of strings (`engine/processing/script.py:122-128,257-273`). That is not a correctness guarantee.

The target design must never reconstruct display text from ASR. Subtitle text must always be a slice of the immutable original script. Normalized tokens are permitted only for matching.

### 5.3 Subtitle chunking

The current chunker is deterministic and dependency-light, but limited to whitespace tokens, 2-8 words, an English conjunction set, and a short punctuation list (`engine/processing/script.py:23-27,160-213`). `split()` and `join()` collapse whitespace. It has no duration, line-length, character-per-second, language, pause, or word-timestamp inputs. An orphan merge may exceed the configured maximum.

The replacement should optimize global cue boundaries using exact script spans, cleaned word timestamps, sentence/paragraph boundaries, preserved source pauses, max lines, max characters, CPS, and duration constraints. Unsatisfied constraints must produce explicit warnings rather than silent rule violations.

### 5.4 Audio cleaning and retiming

No relevant implementation exists. The target should use integer sample indices and half-open ranges `[start_sample,end_sample)` as its canonical time domain. A conservative cut is allowed only inside a signal-confirmed pause and outside every aligned word plus configurable guard margins. Long pauses are shortened by removing the middle, leaving a natural retained pause.

`edit_map.json` must record source and output hashes, audio formats, kept and removed sample spans, retained pause, boundary guards, policy/model/tool versions, remapped words, warnings, and schema version.

### 5.5 Premiere, Resolve, and CapCut

The current exporters are syntactically well-formed in a local pure-core smoke check, but the repository has no DTD validation or real Premiere/Resolve import gate. It supports only integer FPS; 23.976/29.97/59.94 cannot be represented in the Django model (`apps/projects/models.py:29`). Missing timings silently fall back to 2.5 seconds (`engine/export/fcpxml.py:313-346`; `engine/export/premiere_xml.py:274-305`). Production export must reject missing timing instead.

The authoritative editor payload should be one cleaned WAV at time zero plus an authoritative SRT. XML title generation is optional because title/caption translation is editor-specific. Apple states that DTD validity is necessary but not sufficient for successful import, so release gates must include real NLE import/reopen tests ([Apple FCPXML DTD](https://developer.apple.com/documentation/professional-video-applications/document-type-definition)). Adobe confirms that Premiere does not directly import FCPXML, supporting the separate xmeml and FCPXML outputs ([Adobe Premiere guidance](https://helpx.adobe.com/premiere/desktop/organize-media/import-files/migrate-from-final-cut-pro-x.html)).

The safe CapCut path is standards-only: WAV, UTF-8 SRT, edit map, manifest, checksums, and instructions. CapCut Desktop officially supports SRT import ([CapCut subtitle import](https://www.capcut.com/help/how-to-import-subtitles)). A local draft writer must remain experimental, create a new draft only, fail closed on unknown versions, and never mutate a user's existing draft.

## 6. Validation performed during analysis

- PDF pages were rendered to PNG and visually inspected as a 15-page contact sheet.
- Repository structure, imports, requirements, task orchestration, models, tests, and exporters were inspected with file/line evidence.
- A minimal no-bytecode smoke check imported `align_segments`, `build_fcpxml`, and `build_premiere_xml`, generated XML, and parsed both roots successfully.
- Importing the supposedly pure subtitle module in an environment without Celery failed because `config.constants` triggers `config/__init__.py -> config.celery`. This confirms the hidden coupling documented in `DEPENDENCY_MAP.md`.
- The full pytest suite was not run because the analysis environment did not provide pytest and installing production/development dependencies was outside scope.

## 7. LARP theory contribution

The PDF is satirical in tone but contributes useful planning rules:

- route isolated changes of roughly one file and under about 150 lines as Small Tasks;
- route multi-module work, migrations, and integration-test work as Big Tasks;
- use a planner/subagent split for independent analysis;
- treat validation as a mandatory feedback loop;
- end with a concise walkthrough.

It does not define pause detection, alignment, subtitle, NLE, or packaging algorithms. Those decisions come from repository evidence and the target product requirements.

## 8. Extraction verdict

The reference repository should remain immutable. The new product should copy only explicitly selected algorithmic ideas and fixtures into a separately owned core, with provenance recorded. The product is primarily a new implementation, not a backend port.
