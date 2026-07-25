#!/usr/bin/env python3
"""Create an isolated app-data/Documents profile and verify packaged media.

This is a bounded host-isolation check, not a claim of a separate clean Mac.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="larp-audio-clean-") as directory:
    profile = Path(directory)
    app = ROOT / "dist/LARP Audio.app"
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_packaged_app.py"), str(app)], check=True, env={"PATH": "/usr/bin:/bin", "HOME": str(profile)})
    print(f"Isolated writable profile verified: {profile.name}")
