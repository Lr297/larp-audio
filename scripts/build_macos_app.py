#!/usr/bin/env python3
"""Validate pinned resources and build the arm64 application bundle."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("This checked-in spec currently builds macOS arm64 only.")
    manifest = json.loads((ROOT / "resources/bin/manifest.json").read_text())
    expected = manifest["platforms"]["macos-arm64"]
    for name in ("ffmpeg", "ffprobe"):
        path = ROOT / "resources/bin/macos-arm64" / name
        if not path.is_file() or digest(path) != expected[f"{name}_sha256"]:
            raise SystemExit(f"Missing or unverified bundled component: {name}")
    icon = ROOT / "resources/icons/larp_audio.icns"
    if not icon.is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts/build_app_icon.py")], check=True)
    base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    requirements = ROOT / "packaging/requirements-macos-arm64.txt"
    with tempfile.TemporaryDirectory(prefix="larp-packaging-") as temporary:
        environment = Path(temporary) / "environment"
        wheelhouse = Path(temporary) / "wheelhouse"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / "bin/python"
        clean_env = {
            **os.environ,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements)],
            check=True,
            env=clean_env,
        )
        wheelhouse.mkdir()
        subprocess.run(
            [str(environment / "bin/uv"), "build", "--wheel", "--out-dir", str(wheelhouse), str(ROOT)],
            check=True,
            env=clean_env,
        )
        wheels = sorted(wheelhouse.glob("larp_audio_mvp-*.whl"))
        if len(wheels) != 1:
            raise SystemExit("Expected exactly one project wheel in the clean packaging environment.")
        subprocess.run([str(python), "-m", "installer", str(wheels[0])], check=True, env=clean_env)
        site_packages = environment / "lib/python3.12/site-packages"
        forbidden_metadata = [
            *site_packages.glob("larp_audio_mvp-*.dist-info/direct_url.json"),
            *site_packages.glob("*.egg-link"),
            *site_packages.glob("__editable__*"),
        ]
        if forbidden_metadata:
            raise SystemExit("Clean wheel installation unexpectedly produced editable/local-source metadata.")
        subprocess.run(
            [str(python), "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "packaging/larp_audio_macos.spec")],
            cwd=ROOT,
            check=True,
            env=clean_env,
        )
    app = ROOT / "dist/LARP Audio.app"
    subprocess.run([str(base_python), str(ROOT / "scripts/scan_release_privacy.py"), str(app)], cwd=ROOT, check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], check=True)
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
