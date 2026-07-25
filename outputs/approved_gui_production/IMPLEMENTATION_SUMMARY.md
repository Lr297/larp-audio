# Approved GUI production integration

The user-approved, quieter AdsCreativeHouse-inspired prototype is now the
production PySide6 composition.

## Integrated presentation

- near-black `#060606` canvas and neutral `#101010` surfaces;
- focused `#FF3F3D` accent with neutral borders;
- compact editorial header and static workflow strip;
- asymmetric Voiceover / Exact text input composition;
- flat numbered Tight / Balanced / Natural choices;
- one model/output/readiness/Process action strip;
- compact stage-based processing state;
- Preview / Subtitle Blocks / Diagnostics / Files result navigation.

The controller, workers, local processing pipeline, audio/STT/alignment/
subtitle algorithms, persisted schemas, cancellation, preview synchronization,
and desktop file actions were not rewritten.

## Verification

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui`
  — 59 passed.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
  — 437 passed, 4 skipped.
- `.venv/bin/python -m compileall -q src tests scripts` — passed.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/run_stage_12_1_demo.py --smoke`
  — passed.
- Production screenshot generation — passed; main states are 1440×900.
- Reference integrity matches the established baseline:
  - `reference/LARP_theory.pdf`:
    `c98e98b7abf871346d1f673fc1d1d362aa673e9771698f70484d980ae620f3b5`;
  - `reference/ivm_ai_backend` aggregate:
    `12563b847130e956906d9b42a03674189e0b94751fea53757032fb5114c62141`.
- No runtime dependency was added; `pyproject.toml` and the lockfile were not
  changed.

The skipped tests require both local FFmpeg/ffprobe or a complete local
Faster-Whisper model. No formatter or linter is configured in the project.
