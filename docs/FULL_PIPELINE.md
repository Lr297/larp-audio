# Full local desktop pipeline (Stage 11.1)

## Published-run preview validation

Stage 12 does not add a pipeline stage or mutate published artifacts. A background preview-preparation pass validates WAV, edit map, recognition, alignment, subtitle blocks, SRT, processing report, manifest and ZIP provenance before loading cleaned audio. The package manifest is parsed by the canonical disk/ZIP validator, and an external manifest must match the archive copy byte-for-byte when both are supplied.

## Scope and workflow

Stage 11 connects the existing audio, pause, recognition, alignment and subtitle
components behind one `FullProcessingService`. The user selects source audio,
provides the exact original script, selects an explicitly prepared local
Faster-Whisper directory and an output parent, then chooses **Create Subtitle
Package**. A successful run contains `cleaned_audio.wav`, `edit_map.json`,
`recognition.json`, `alignment.json`, `subtitle_blocks.json`, `subtitles.srt`,
`processing_report.json`, `manifest.json` and `voiceover_package.zip`.

No cloud service, model download, account, telemetry or browser processing is in
this path.

## Architecture and order

`PipelineRunRequest` carries source paths, immutable `ScriptInput`, validated
audio/pause/model/alignment/subtitle settings and application version.
`FullProcessingService` is the single complete-workflow orchestration entry;
adapters are constructor-injected. The order is analysis/canonicalization →
pause detection → existing shortening/rendering → edit map → local STT on the
cleaned WAV → exact-script alignment → subtitle blocks → cleaned-timeline SRT →
strict validation → reports/manifest/package → atomic publication. Algorithms
are not duplicated in the orchestrator.

`PipelineStage` provides typed phases. `PipelineProgress` reports stage, step X
of Y, detail, indeterminate flag and cancellation state. Stage count is not a
false estimate of elapsed time.

## Exact ScriptInput

`ScriptInput` records exact Unicode, source kind/path, UTF-8/BOM metadata,
newline style, counts, SHA-256 and GUI-edit provenance. UTF-8 files are decoded
from bytes explicitly. LF, CRLF, CR, Unicode separators and trailing newlines
are retained in the backend model. Qt display normalization does not replace the
loaded model until an actual edit signal creates a new exact value and hash.
Empty, whitespace-only, wordless, invalid UTF-8 and inputs over 500,000
characters are rejected; text is never truncated or normalized.

ASR text is comparison evidence only. Alignment/subtitles retain script text,
and SRT is rendered only from `SubtitleDocument` on the cleaned timeline.

## Local tools and model

Production composition reuses `ExecutableResolver`, ffprobe, canonical converter,
silence detector and FFmpeg renderer. Tools are actually executed in preflight;
subprocess arguments remain lists, `shell=False`, with timeouts. Development can
use explicit paths or PATH fallback; a later packaged build must bundle tools.

The model directory is explicit and must contain `config.json`, `model.bin` and
`tokenizer.json`. Faster-Whisper receives it with `local_files_only=True`. Missing
or incomplete models fail without Hugging Face lookup, network fallback or
automatic download. Existing tiny/base/small, device and compute settings apply.

## Staging, path safety and publication

Run names use a sanitized bounded audio stem and UTC timestamp. Windows-illegal
characters, control characters, trailing dots/spaces and traversal are removed;
collisions receive `_2`, `_3`, etc. A hidden `.run.run-id.partial` directory is
created beside the final directory. Symlink output parents and collisions are
rejected.

All artifacts are created and strictly read in staging. Publication begins only
after package validation, disables cancellation, and uses `os.replace` into a
destination that must not exist. Error/cancellation cleans staging best-effort
and never publishes a partial final directory. Source audio, script and model
are read-only.

## Cancellation and GUI lifecycle

`CancellationToken` is thread-safe and checked around every stage and before ZIP
and publication. Synchronous FFmpeg/Faster-Whisper work may finish its current
step before cancellation is observed; the GUI says this explicitly. No
`QThread.terminate()` is used. `FullProcessingWorker` never accesses widgets.
The controller keeps pending outcomes in `FINISHING`; `SUCCESS`, `CANCELLED` or
failure is published only after `QThread.finished` clears worker/thread. Inputs
survive failure/cancellation. Stage 10.1 active failures, Dismiss, Copy Details,
clipboard privacy, path elision and warning filter remain active.

## Persisted schemas and package

`processing_report.schema.v2` stores run/app/time/platform metadata, source
filename/hash/size, script hash/counts, hashed configuration, ordered stages,
warnings, artifacts and metrics. Technical metrics cover source format/codec,
sample rate/channels, original/cleaned/removed sample totals, detected and
shortened pauses, local model identity (hash plus directory basename, never its
absolute path), recognition, alignment and subtitle diagnostics. It excludes
exact script, audio/model content and model absolute path. Its strict reader
checks schema, the complete pre-report stage sequence, per-stage and overall
elapsed timestamps, status consistency, artifact references, warning totals,
the recomputed configuration hash, unique metrics and sample-total equations.
The persisted report describes stages completed before report serialization;
package creation and atomic publication remain available in the returned
`PipelineRunResult.stage_results`, avoiding a recursive rewrite of a report
already hashed by the manifest and embedded in ZIP.

`manifest.schema.v1` lists required artifacts except itself and ZIP to avoid
recursive hashes. Entries contain safe relative path, role/media/schema/timeline,
streamed SHA-256 and size. Validation rejects absolute/`..`/duplicate/outside,
missing or modified entries, incorrect JSON schema metadata, unexpected file
order and inconsistent totals. The fixed list is cleaned WAV, edit map,
recognition, alignment, subtitle blocks, SRT and processing report; manifest and
package names are metadata rather than self-referential entries.

`voiceover_package.zip` contains the eight deliverables other than itself, in a
fixed order using DEFLATE and fixed 1980 timestamps. It excludes source audio,
canonical temp audio, models, logs and staging names. Validation checks CRC,
exact safe list, report/manifest provenance consistency and every embedded
manifest size/hash.

## Stage 11.1 publication integrity

Published JSON and ZIP artifacts contain no absolute input, model, workspace,
temporary, or developer paths. `PublishedSourceReference` carries only a safe
basename, logical role, content SHA-256, source kind, original extension, and
script BOM/newline metadata. Runtime-only paths remain in the request/result
objects and, only when manual action is required, the in-memory cleanup outcome.
The alignment script `source_path` is a safe basename; exact script text remains
unchanged.

The request `local_model_path` is canonical. The deprecated duplicate
`ModelSettings.model_path` may be absent; when present it must resolve to the
same directory. The model and output parent may not equal or contain one
another in either direction. These checks run before tools, model inference, or
staging creation.

Failures carry immutable `PipelineCleanupOutcome`. The stage failure always
remains primary. Cleanup is attempted only for a created staging directory and
physical existence is checked afterward. Cleanup failure is a secondary code,
residual flag, warning, and runtime-only residual path. GUI/CLI therefore never
claim cleanup succeeded based only on intent.

`processing_report.schema.v2` replaces ambiguous `started_at`, `completed_at`,
and `elapsed_milliseconds` with `processing_started_at`,
`report_generated_at`, and `processing_elapsed_milliseconds`. Durations come
from a monotonic clock; UTC timestamps are descriptive and are not used to
recompute elapsed time after a system-clock adjustment. Version 1 is explicitly
rejected. `manifest.schema.v1` remains compatible but references report schema
v2. `alignment.schema.v2` remains unchanged because safe source-kind/newline
metadata is additive and optional for legacy v2 reads.

Analysis, canonicalization, shortening-plan creation, and cleaned-audio render
are real separate calls and stages. No synthetic zero-duration stage record is
inserted. Failed/cancelled operations are closed with their real status, code,
wall timestamp boundaries, and monotonic duration. The persisted report covers
preflight through core validation; `published_at` is runtime-only.

## Cross-artifact provenance and ZIP streaming

Before the report and again before the package, strict readers plus
`validate_pipeline_artifact_set()` verify that cleaned WAV SHA-256 equals the
edit-map output hash; canonical WAV equals the edit-map source hash while that
temporary file exists; recognition metadata binds cleaned audio/edit map;
alignment embeds the standalone recognition/edit map; subtitles bind the
alignment hash and exact script; and all components share exact sample rate and
original/cleaned totals. Report and manifest bind uploaded source-audio hash,
script hash, configuration, run id, version, and timeline metrics. Uploaded
source hash and canonical timeline-source hash are deliberately distinct when
conversion was required. SRT is validated on the cleaned timeline.

ZIP validation never calls `ZipFile.read()`. It reads 1 MiB chunks while
counting and hashing, and rejects unsafe/duplicate/encrypted entries,
unsupported compression, over-expansion, or declared/actual size mismatch.
Limits are 32 entries, 24 GiB per entry, 32 GiB total uncompressed, 16 MiB per
JSON metadata document, and a 2000:1 compression ratio. Every embedded JSON is
also scanned for generic absolute-path leakage.

## CLI and testing

GUI and `larp-audio-process` call the same service. CLI accepts mutually exclusive
`--script-file`/`--script-stdin`, writes typed progress to stderr and JSON summary
to stdout; expected errors have stable codes without traceback.

```bash
uv run larp-audio-process --audio voice.mp3 --script-file script.txt \
  --model tiny --model-path /local/models/tiny --output-parent ./outputs
```

Offline integration uses synthetic WAV/timing adapters plus real alignment,
subtitle, report, manifest, ZIP and publication. Optional FFmpeg/model tests skip
rather than download. Demo recognition is explicitly synthetic and includes an
ASR insertion verified absent from SRT.

Stage 12 may address packaging, bundled tools in installed builds, corpus
calibration and richer external-process cancellation. Player/waveform, subtitle
editing, XML/NLE and CapCut Draft remain out of scope.
