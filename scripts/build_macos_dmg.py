#!/usr/bin/env python3
"""Create the Finder-installable Stage 14 release-candidate DMG."""

import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0-rc.9"
app = ROOT / "dist/LARP Audio.app"
destination = ROOT / f"dist/LARP-Audio-{VERSION}-macOS-{platform.machine()}.dmg"
if not app.is_dir():
    raise SystemExit("Build dist/LARP Audio.app first")
with tempfile.TemporaryDirectory(prefix="larp-audio-dmg-") as temporary:
    temporary_root = Path(temporary)
    staging = temporary_root / "staging"
    staging.mkdir()
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications", target_is_directory=True)
    read_write = temporary_root / "LARP-Audio-rw.dmg"
    subprocess.run(
        ["hdiutil", "create", "-volname", "LARP Audio RC", "-srcfolder", str(staging), "-ov", "-format", "UDRW", str(read_write)],
        check=True,
    )
    mountpoint: Path | None = None
    attached = False
    try:
        attach = subprocess.run(
            ["hdiutil", "attach", "-readwrite", "-plist", str(read_write)],
            check=True,
            capture_output=True,
        )
        metadata = plistlib.loads(attach.stdout)
        mount_values = [entity.get("mount-point") for entity in metadata.get("system-entities", []) if entity.get("mount-point")]
        if len(mount_values) != 1:
            raise RuntimeError("Could not determine the writable DMG mount point")
        mountpoint = Path(mount_values[0])
        attached = True
        layout_script = '''
tell application "Finder"
  tell disk "LARP Audio RC"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set bounds of container window to {120, 120, 760, 520}
    set arrangement of icon view options of container window to not arranged
    set icon size of icon view options of container window to 112
    set position of item "LARP Audio.app" of container window to {175, 190}
    set position of item "Applications" of container window to {465, 190}
    update without registering applications
    delay 2
    close
  end tell
end tell
'''
        subprocess.run(["osascript", "-e", layout_script], check=True, text=True)
        for generated_name in (".fseventsd", ".Spotlight-V100", ".Trashes"):
            generated = mountpoint / generated_name
            if generated.is_dir():
                shutil.rmtree(generated)
            elif generated.exists():
                generated.unlink()
    finally:
        if attached and mountpoint is not None:
            subprocess.run(["hdiutil", "detach", str(mountpoint)], check=True, capture_output=True)
    temporary_destination = destination.with_suffix(".partial.dmg")
    subprocess.run(
        ["hdiutil", "convert", str(read_write), "-format", "UDZO", "-imagekey", "zlib-level=9", "-o", str(temporary_destination)],
        check=True,
    )
    os.replace(temporary_destination, destination)
print(destination)
subprocess.run([sys.executable, str(ROOT / "scripts/scan_release_privacy.py"), str(destination)], cwd=ROOT, check=True)
