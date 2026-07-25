# Stage 10 desktop GUI

## Stage 13 consumer setup

The normal one-page workflow shows **Speech engine: Ready / Setup required** and
an automatic results location. It never asks for a model directory or requires
an output folder before processing. One setup dialog downloads and verifies the
pinned local timing engine. Check, Repair, Remove and optional result-location
override live in Advanced Settings. The approved Stage 12.1 visual hierarchy
and Preview/Subtitle Blocks/Diagnostics/Files behavior are retained.

## Stage 12.1 production one-page redesign

The current product surface is no longer the Stage 10 technical form. The
approved high-contrast editorial composition contains asymmetric Audio and
Script inputs, three numbered pause choices, one setup/action strip, a compact
processing state, and inline result tabs. Exact numeric controls remain in a
closed-by-default Advanced Settings dialog. The window supports 1100×760
through 1440×900 without horizontal page scrolling.

`production_workspace.py` composes the current widgets; `design/` owns tokens,
stylesheet, icons, and reusable cards/header/status components. `MainWindow`
continues to render the existing immutable controller state and invoke the
existing Stage 11/12 pipeline—no backend algorithm or output schema was copied
into the view.

The canonical pause presets are centralized and immutable in `presets.py`:

| Preset | threshold | detected silence | shorten from | retained | max removed |
|---|---:|---:|---:|---:|---:|
| Tight | -50 dB | 200 ms | 350 ms | 120 ms | 1500 ms |
| Balanced | -50 dB | 300 ms | 500 ms | 200 ms | 1000 ms |
| Natural | -55 dB | 400 ms | 800 ms | 350 ms | 700 ms |

Balanced is the default. Editing any exact pause value marks the UI as Custom;
choosing a preset reapplies every value. Restore All Defaults returns pause,
speech, subtitle, and output settings to their existing contract defaults. See
`ONE_PAGE_GUI.md` for the complete production UX contract.

## Stage 12 result workspace

The lower result workspace is tabbed into Preview, Subtitle Blocks, Diagnostics and Artifacts. The Original Script input uses a resizable vertical splitter and the page remains scrollable at 1100×760. Preview preparation is a background task; media position updates and binary cue lookup stay lightweight on the GUI thread. Preview errors use the unified recoverable failure banner and retain the successful run. See [PREVIEW_AND_DIAGNOSTICS.md](PREVIEW_AND_DIAGNOSTICS.md).

## Stage 11.1 preflight, settings, and cleanup truthfulness

After local audio selection a dedicated read-only ffprobe worker shows
format/container, duration, sample rate, channels, codec, and file size without
canonicalization and without blocking the GUI thread. A recoverable ffprobe
failure retains the chosen audio but disables processing until corrected.

The Processing Settings group constructs the same immutable settings objects as
the backend. It exposes silence threshold, minimum detected silence, minimum
pause to shorten, retained pause, maximum removal, recognition language and
beam size; model/device/compute controls remain authoritative. Baseline pause
values live in `desktop_mvp_pause_settings()`, not in `MainWindow`.

Full-pipeline failures display the primary stage error separately from cleanup.
Details state whether cleanup was attempted/completed and whether a residual
workspace exists. A residual absolute path appears only in local explicit error
details so the user can remove it; it is never serialized into published JSON
or ZIP. Cancellation uses the same outcome. Dismiss retains audio, script,
model, and output selections for retry.

Progress messages come from the operation currently executing. Source analysis,
canonical conversion, pause planning, cleaned-audio render, local recognition,
alignment, subtitles, validation, ZIP, and publication are distinct. The bar
shows completed pipeline stages and “step X of 14” is an operation count, not a
fabricated time percentage.

## Stage 11 primary workflow

The primary screen now accepts Audio File, exact Original Script, Local Model
and Output Folder. It supports audio drag/drop, UTF-8 TXT loading, counters,
tiny/base/small/device/compute choices, typed progress, cooperative Cancel,
artifact actions and the subtitle table. Prepared alignment remains a backend
developer workflow, but is no longer required from normal users. Full lifecycle
and publication rules are in `FULL_PIPELINE.md`.

## Stage 10.1 correction

`GuiState` is the only source for workflow phase, alignment, output directory,
task activity, result, warnings, progress, and `active_failure`. A recoverable
failure coexists with `EMPTY`, `READY`, or `SUCCESS`; `Dismiss` removes only that
failure, so a successful table and its paths survive a desktop action error.
`Copy Details` formats the current failure on explicit request. Merely showing an
error never changes the clipboard.

The controller tracks `created`, `running`, backend outcome, `finishing`, and
`idle`. Backend signals store a pending result/failure. Controls remain locked
through `PROCESSING` and `FINISHING`; `SUCCESS` (or a recoverable backend failure)
is published only by `QThread.finished` after worker/thread references are
cleared. Closing during either active phase is declined without `terminate()`.

`Show warnings only` is implemented with `QSortFilterProxyModel`; it filters the
view for explicit, interpolated, or unresolved warnings and displays `Showing X
of Y` without modifying `SubtitleDocument`. Paths use middle elision via
`QFontMetrics`; the complete value remains in `GuiState`, appears in the tooltip,
and is copied through `Copy Full Path`.

Settings, drop, dialog, desktop, and unexpected local failures all enter the
same controller failure channel. Tracebacks stay in logs, not in UI details.
The prepared-`alignment.json` path remains as a legacy developer workflow. The
primary Stage 11 panel uses source audio, exact script, local model and output
folder and is the normal user entry point.

## Scope

LARP Audio Stage 10 is the first working Windows/macOS-oriented desktop
interface. It accepts an existing strict `alignment.schema.v2`, lets the user
choose an output folder, runs the Stage 9.1 subtitle backend, and previews the
resulting `subtitle_blocks.json` and `subtitles.srt`.

It does not load audio, run FFmpeg, shorten pauses, run Whisper, create an
alignment, play audio, draw a waveform, export XML/CapCut, package an installer,
or pretend that those stages already exist. Stage 11 may connect the established
audio-to-alignment components to this application shell.

## Architecture

The GUI is a one-way presentation layer over existing contracts:

```text
MainWindow (Qt Widgets)
       ↓ user intent / state rendering
GuiController + immutable GuiState
       ↓ GenerationRequest
QThread + SubtitleGenerationWorker
       ↓ direct Python API call
SubtitleGenerationService (Stage 9.1)
       ↓
strict SubtitleDocument + SRT validation
```

- `main_window.py` owns layouts and renders state; it does not parse JSON or
  write artifacts.
- `state.py` defines the explicit phase enum and immutable summaries/results.
- `controller.py` loads alignment through `read_alignment()`, validates state,
  owns one worker/thread, and publishes transitions.
- `workers.py` is the only background boundary and calls the existing service.
- `models.py` provides a read-only `QAbstractTableModel` for subtitle blocks.
- `dialogs.py` and `desktop.py` isolate native dialogs and desktop actions so
  they can be faked in tests.
- `theme.py` contains the central dark QSS theme.

No backend algorithm was copied into the GUI. Stage 10 does not change
alignment, subtitle segmentation, wrapping, SRT rounding, validation, or the
two-output transaction.

## State model

`GuiPhase` contains `empty`, `loading_alignment`, `ready`, `processing`,
`success`, and `error`. `GuiState` contains the current paths, strict alignment,
presentation summary, generated document, stage message, safe error and
warnings. Controls derive from this single state:

- empty/error-without-input: select alignment; generation disabled;
- ready/success: selection/settings/generation enabled;
- processing: alignment/output/settings/generation disabled and an
  indeterminate progress bar visible;
- generation error with a retained valid alignment: controls recover for retry.

Two runs cannot coexist in one controller. A second generate request returns
`False`. Closing while processing is ignored with a clear status message; Qt
threads are never force-terminated.

## Alignment and display text

Browse and drag/drop both call the same strict `read_alignment()` path. A drop
accepts exactly one local regular file, never starts generation automatically,
and rejects directories, multiple URLs and non-local URLs. Corruption and
unsupported schemas become a recoverable error state.

The preview reads `AlignmentResult.script.exact_text`. The backend string stays
unchanged. Qt may visually represent CRLF using its native paragraph separator;
the GUI never writes preview contents back to the alignment or output.

The summary shows script/ASR/matched/interpolated/unresolved word counts,
alignment/timing coverage, sample rate, cleaned duration, provenance completeness,
schema and warning count. Raw JSON and recognition text are not the primary UI.

## Output and path safety

The default output is an uncreated `outputs` sibling directory beside the
alignment. The GUI displays the fixed safe filenames `subtitle_blocks.json` and
`subtitles.srt`. Directory creation is deferred to
`SubtitleGenerationService`, so the immutable Stage 9.1 `SubtitlePathPlan`
remains authoritative for normalized/symlink/hard-link collision checks,
staging, publication and rollback.

The GUI calls the service directly, not the CLI subprocess. The result table
uses canonical block order and exposes cue number, cleaned start/end/duration,
display text, words, exact rational-derived CPS, timing provenance and a textual
warning marker. JSON keeps both timelines; SRT continues to use cleaned time.

## Threading and progress

Generation runs in a `SubtitleGenerationWorker` moved to one `QThread`. Signals
carry `started`, stage messages, success/failure and `finished`; the worker never
accesses widgets. The progress bar is indeterminate, not a fabricated percent.
Stage messages cover alignment validation, output preparation, block/artifact
generation, result validation and completion. Alignment loading is a bounded
strict JSON read on the controller; the artifact-generating operation is outside
the UI thread.

## Errors

Known `ProjectError` values retain their stable code and safe message. The GUI
shows an error banner with text label, Copy Details and Dismiss; it does not show
a traceback. Unexpected worker exceptions are logged through the existing
logging infrastructure and surfaced as sanitized `GUI_INTERNAL_ERROR`. Desktop
open failures use `DesktopActionError`. Script and raw alignment contents are
not logged.

## Desktop actions

Open Folder/Open SRT/Open JSON use `QDesktopServices.openUrl()` with
`QUrl.fromLocalFile()`. No shell, `os.system`, platform-specific command or
subprocess is constructed. Copy actions use the Qt clipboard.

## Advanced settings

The collapsible Advanced Settings panel exposes only existing
`SubtitleSettings`: characters/line, max lines, max words, preferred minimum
duration, hard maximum duration and maximum CPS. Construction of the existing
immutable settings contract performs validation immediately. Hidden scoring
defaults come from `SubtitleSettings()` at use time; no second default table or
raw TOML UI exists. Restore Defaults reads the same contract.

## Theme and accessibility

The central theme uses the audited `#060606` canvas, `#101010` surfaces,
`#232323` boundaries, visible focus, textual disabled/error/success states, and
the approved `#FF3F3D` accent. Arial Black/Arial and Helvetica Neue/Helvetica/
Arial are system substitutes for the reference display/body fonts; no font
files, images, or icon packs are bundled. Earlier violet and burgundy accents
are no longer part of production QSS.

Layouts are resizable, start at 1200×760 and have a 960×640 minimum, so primary
controls remain available at 1024×700, 1280×800 and 1440×900. Buttons are in tab
order, have accessible names/tooltips, support keyboard activation, and the
default Generate button accepts Enter when safe. The subtitle table is read-only,
row-selectable, resizable, wrapped, tooltip-enabled and supports Ctrl+C.
Warning/Error/Success are textual labels, not color-only signals.

## Safe UI preferences

`QSettings` stores only window geometry, last output directory, advanced-panel
state and may later store column widths. It does not store script text,
alignment/ASR JSON, error tracebacks, or automatically reload a previous
alignment. The last alignment path is intentionally not persisted.

## Development launch

Install the locked environment and start the application:

```bash
uv sync --frozen
uv run --frozen larp-audio-gui
# equivalent
uv run --frozen python -m larp_audio_mvp.app.desktop
```

The demo prepares synthetic Stage 10 artifacts with the real backend and opens
the ready state without FFmpeg, Whisper, a model or network:

```bash
uv run --frozen python scripts/run_gui_demo.py
```

Automated offscreen smoke/screenshots:

```bash
QT_QPA_PLATFORM=offscreen uv run --frozen python scripts/run_gui_demo.py --smoke
QT_QPA_PLATFORM=offscreen uv run --frozen python scripts/run_gui_demo.py --screenshots
QT_QPA_PLATFORM=offscreen uv run --frozen pytest tests/gui tests/integration/test_desktop_gui.py
```

## PySide6 dependency decision

Direct runtime dependency: `PySide6>=6.8.3,<6.9`; lockfile resolves 6.8.3 with
matching `shiboken6`, `pyside6-essentials` and `pyside6-addons`. Qt Widgets is
required by the Stage 10 product decision and cannot be supplied by the standard
library. PySide6 is published under LGPLv3/GPLv2/GPLv3 and commercial options;
distribution must preserve applicable Qt/LGPL notices and relinking obligations.

It introduces large native Qt binaries (roughly 400+ MiB downloaded for this
development environment), platform-specific wheels, additional CVE/update work,
and future PyInstaller signing/notarization considerations. It does not download
data or models at runtime. The `<6.9` cap prevents an unreviewed Qt minor upgrade;
future upgrades require GUI/offscreen/package tests. Removal consists of deleting
the `gui`/desktop entry point and dependency. Packaging is deliberately deferred.

`pytest-qt` was not added. Qt `QTest`, signals and offscreen event processing are
sufficient, avoiding another dependency.

## Known limitations and Stage 11 boundary

- Only a prepared alignment can be selected.
- No cancellation is needed for the current short subtitle job; close is safely
  blocked while it runs.
- Alignment loading is synchronous; exceptionally huge JSON may briefly delay
  rendering and can move to a loader worker if real-world evidence requires it.
- Cross-file publication remains best-effort as documented by Stage 9.1.
- No installer or packaged-resource verification exists yet.
- Windows/macOS native visual QA and accessibility-tool audits remain future
  release work; offscreen Qt tests cover functional layout/state behavior.

Stage 11 may add application-level orchestration for existing ingestion, pause,
STT and alignment stages. It must reuse their contracts and worker boundaries;
this Stage 10 screen does not contain placeholders that falsely claim those
features are available.
