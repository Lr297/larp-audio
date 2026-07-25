# Preview and diagnostics

## Stage 12.1 result presentation

Preview, Subtitle Blocks, Diagnostics, and Files now open inline beneath the
one-page inputs. A successful run opens Preview once; switching tabs or clicking
**Reload Preview** never changes published artifacts. Initial preview volume is
80%. The left cue list keeps keyboard selection separate from the red-tinted
currently playing cue, and **NOW PLAYING** clearly labels the current subtitle.
Previous/Next, play/stop, seek, volume, mute, and auto-scroll remain functional.

The Subtitle Blocks table intentionally shows only Block, Time, Text, Words,
CPS, and Warning. Diagnostics begins with cleaned duration, block count,
warnings, and coverage before the detailed log. Files uses human names and
explicit open/copy/show actions; full local paths are never printed as primary
page content.

Stage 12 adds a read-only local preview of the already published `cleaned_audio.wav` synchronized with the canonical `subtitle_blocks.json`. It does not edit, render, rewrite, or republish any artifact.

## Stage 11.2 hardening gate

Audio preflight requests now carry a unique request ID, normalized path identity, sequence number, and optional stat snapshot. A result is applied only to the current request and path; older success and failure callbacks are ignored. Selecting another file immediately clears old metadata and disables processing. Workers finish naturally and are never terminated.

Cleanup wording is factual. A failure before service construction says that no workspace was created. A failure after service construction without a `PipelineCleanupOutcome` says that cleanup status is unavailable. Only a real outcome can claim attempted/completed cleanup or a residual workspace. The CLI prints the local residual path only when a residual exists and the path is known.

The Original Script editor has a 100 px minimum, a preferred 145 px initial pane, a vertical resize handle, and a scrollable main page. The supported minimum window is 1100×760.

Successful `processing_report.schema.v2` files accept only the exact required ordered success stages, no stage error codes, monotonic wall timestamps, a report timestamp after the stages, a total elapsed value no shorter than the sum of monotonic stage durations, and recomputed warning/artifact totals. Cancelled or failed runs are not published as successful package reports. Wall-clock timestamp differences are not equated to monotonic elapsed measurements because clock adjustments would make that comparison false.

`manifest.schema.v1` uses one canonical parser for disk and ZIP copies. It verifies the exact path/role/media type/required/timeline/schema matrix, counts, bytes, hashes, safe paths, JSON schemas, report provenance, privacy and cross-artifact timeline/provenance invariants. An external manifest, when supplied, must match the ZIP copy byte-for-byte.

## Architecture

- `MediaBackend` owns transport operations and events. Unit tests use a fake.
- `QtMediaBackend` lazily imports `QMediaPlayer` and `QAudioOutput`; unavailable multimedia raises `PREVIEW_MULTIMEDIA_UNAVAILABLE` without breaking application import.
- `PreviewPreparationService` validates the complete run and creates `PreviewSource` plus diagnostics. `PreviewPreparationWorker` keeps hashing and ZIP validation off the UI thread.
- `PreviewController` owns high-frequency playback state and session identity. Stale callbacks from replaced sessions are ignored.
- `SubtitleSynchronizer` performs immutable O(log n) lookup.
- `PreviewPanel` is a widget-only transport/cue view; `MainWindow` centrally renders preview state and keeps the pipeline result authoritative.

## Timeline and cue boundaries

Only the cleaned timeline is used for playback. Integer conversion is `position_sample = floor(position_milliseconds × sample_rate / 1000)`.

A cue is active on the half-open interval returned by the canonical
`apply_gapless_display_timing()` policy. A non-final interval is
`[speech_start_sample, next_cue_start_sample)` and the final interval is
`[speech_start_sample, cleaned_total_samples)`. The first cue is never moved
before its valid start. At the exact next start only the next cue is active;
internal gaps do not create an empty main Preview state. Real speech end remains
unchanged in the subtitle block/provenance data; Preview and the subtitle table
show the derived display interval.

New v4 results display only the validated `display_text`: ordinary terminal
ASCII periods are hidden, ellipses and meaningful internal dots remain, and no
block exceeds 45 characters including spaces. The exact source span is retained
in the result JSON and is never replaced by ASR text.

`PreviewPanel` renders cue text as plain text in a width-aware vertical surface.
It recalculates height after cue changes and resize, never elides text, disables
horizontal scrolling, and shows a vertical scrollbar only when exceptional text
is taller than the available viewport.

Double-clicking a subtitle row seeks to its cleaned start and does not start playback. Next goes to the next cue. Previous goes to the current cue start when more than 750 ms inside it, otherwise to the preceding cue. Stop returns to zero. Slider seek is applied on release and preserves playback state.

Active and selected rows are separate controller fields. Auto-scroll reveals a visible active proxy row. If the warnings-only filter hides that row, the cue remains active and the panel explicitly reports that it is hidden.

## Errors and lifecycle

Missing/corrupt files, multimedia/plugin failures, missing audio output and failed preparation are controlled preview failures. They never change a successful pipeline run into a failed run and never remove artifact/diagnostic access. The cleaned WAV can still be opened externally. Starting another run resets the media source. Closing stops, clears, disconnects and disposes the backend; active preparation prevents premature window destruction.

Diagnostics are labelled `INFO`, `SUCCESS`, `WARNING`, or `ERROR` and come from validated reports/documents. The Artifacts tab shows portable filenames and sizes; full local paths remain available only through explicit actions/tooltips.

## Testing and limitations

Primary playback tests use a fake backend and need no audio device, model, FFmpeg or internet. The real QMediaPlayer smoke test is optional and skips with the local backend reason when headless multimedia cannot load. There is no waveform, subtitle editing, source-audio comparison, video preview, alternate tracks or export from preview. Those are outside Stage 12.
