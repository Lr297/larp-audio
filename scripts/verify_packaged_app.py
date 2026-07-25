#!/usr/bin/env python3
"""Read-only packaged-resource verification, independent of PATH."""

import json
import subprocess
import sys
from pathlib import Path

app = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/LARP Audio.app").resolve()
media = app / "Contents/Frameworks/bin/macos-arm64"
if not (media / "ffmpeg").is_file():
    raise SystemExit("Bundled ffmpeg is missing from the frozen resource root")
values = {}
for name in ("ffmpeg", "ffprobe"):
    completed = subprocess.run([str(media / name), "-version"], capture_output=True, text=True, timeout=10, env={"PATH": ""})
    if completed.returncode: raise SystemExit(f"{name} failed: {completed.stderr[:300]}")
    values[name] = completed.stdout.splitlines()[0]
application_executable = app / "Contents/MacOS/LARP Audio"
application_check = subprocess.run(
    [str(application_executable), "--verify-installation"],
    capture_output=True,
    text=True,
    timeout=30,
    env={"PATH": "", "HOME": str(app.parent / ".isolated-home")},
)
if application_check.returncode:
    raise SystemExit(f"Frozen application resource check failed: {application_check.stderr[:500]}")
frozen_payload = json.loads(application_check.stdout)
syntax = frozen_payload.get("syntax", {})
if syntax.get("mode") != "spacy_en_core_web_sm" or syntax.get("model") != "en_core_web_sm":
    raise SystemExit("Frozen application did not load its bundled English syntax model")
print(json.dumps({"app": str(app), "media": values, "frozen_check": frozen_payload}, indent=2))
