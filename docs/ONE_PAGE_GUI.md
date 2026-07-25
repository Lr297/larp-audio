# One-page desktop GUI

Stage 12.1 replaces the accumulated technical form with one production-oriented
workspace while preserving the Stage 11 pipeline and Stage 12 preview.

## Product flow

1. Select or drop voiceover audio. The card displays only the filename and safe
   technical metadata; Replace and Remove are explicit actions.
2. Paste or load the exact original UTF-8 script. The editor is the dominant
   input, remains resizable, and reports character and word counts.
3. Choose Tight, Balanced, or Natural pause style.
4. Confirm the local speech model and result folder in Setup.
5. Process. Inputs lock while the existing background worker reports human
   stage names and warnings. Cancel remains cooperative.
6. Inspect Preview, Subtitle Blocks, Diagnostics, and Files inline.

Start over stops/clears preview, clears audio, script, run state, and results,
and returns the pause style to Balanced. It deliberately preserves the local
model and output folder so the next project does not require setup again.

## Design system

The approved reference-derived tokens use canvas/secondary/card/elevated/hover
surfaces `#060606`, `#0B0B0B`, `#101010`, `#161616`, and `#1D1D1D`. Text uses
`#F2F2F2`, `#CFCFCF`, `#9A9A9A`, and disabled `#555555`.
Primary/hover/pressed/deep red are `#FF3F3D`, `#FF5A51`, `#D92F2D`, and
`#B3221F`. Red is reserved for focus, the active pause option, current
processing state, progress, and the primary action. Most boundaries remain
neutral `#232323`. Success, warning, and error retain textual labels and are
never communicated by color alone.

The reference uses Archivo Black/Archivo and Inter. Production does not bundle
those fonts: display text uses the closest available `Arial Black`/Arial system
stack and body text uses Helvetica Neue/Helvetica/Arial. No external font,
image, or icon dependency is loaded.

Reusable pieces live under `gui/design/`: tokens, one central stylesheet,
symbols, waveform painting, editorial pause choices, surface cards, the compact
local status, workflow strip, and main header. The production page composition
lives in `production_workspace.py`; controller, workers, pipeline, serializers,
and output schemas remain authoritative and unchanged.

The supported minimum window is 1100×760. The page scrolls vertically and its
horizontal scrollbar is disabled; 1100×760, 1360×860, and 1440×900 are covered
by offscreen regression screenshots.

## Pause presets

Preset values are one immutable mapping in `gui/presets.py`.

| Preset | Silence threshold | Minimum detected pause | Minimum pause to shorten | Remaining pause | Maximum removed |
|---|---:|---:|---:|---:|---:|
| Tight | -50 dB | 200 ms | 350 ms | 120 ms | 1500 ms |
| Balanced | -50 dB | 300 ms | 500 ms | 200 ms | 1000 ms |
| Natural | -55 dB | 400 ms | 800 ms | 350 ms | 700 ms |

Balanced is selected by default. Selecting a preset updates all five existing
pause settings atomically. Editing any of those values in Advanced Settings
changes the visible state to Custom; selecting a named preset again restores
its exact mapping. These are presentation presets over existing validated
settings, not a parallel processing policy.

## Advanced Settings

The dialog is closed by default and contains four tabs:

- Pause: only the exact five pause parameters used by the existing backend.
- Speech: model, device, compute type, language, and beam size.
- Subtitles: only the existing `SubtitleSettings` controls.
- Output: project basename plus existing safe output behavior.

Apply passes values through the same immutable configuration contracts used by
the pipeline. Restore All Defaults reads those contract defaults and the
Balanced preset. There is no raw TOML editor, second config store, or hidden
algorithm control.

## Result behavior

A successful run reveals the result tabs and automatically enters Preview once.
Initial volume is 80%. Preview reload is explicit; stale preparation callbacks
are ignored and current successful artifacts remain available after a preview
failure. The active cue is visually distinct from the selected cue and follows
playback without changing table selection.

The subtitle table uses the six user-facing columns Block, Time, Text, Words,
CPS, and Warning. Diagnostics starts with a concise summary and retains detailed
validated entries. Files lists human artifact names and exposes safe desktop or
clipboard actions instead of making absolute paths the primary display.

## Development verification

```bash
QT_QPA_PLATFORM=offscreen uv run --frozen pytest tests/gui
QT_QPA_PLATFORM=offscreen uv run --frozen python scripts/run_stage_12_1_demo.py --smoke
QT_QPA_PLATFORM=offscreen uv run --frozen python scripts/run_stage_12_1_demo.py --screenshots
```

The demo constructs the real production widgets over deterministic synthetic
Stage 12 artifacts. It does not invoke FFmpeg, Whisper, a model, an audio device,
or the network.

## Deliberate exclusions

Stage 12.1 does not change audio processing, STT, alignment, chunking, output
schemas, CLI contracts, or the local-only privacy model. It adds no waveform,
subtitle editor, XML exporter, CapCut integration, updater, installer, model
manager, telemetry, cloud service, or mock product surface.
