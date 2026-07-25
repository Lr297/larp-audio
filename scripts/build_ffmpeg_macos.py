#!/usr/bin/env python3
"""Build the pinned LGPL FFmpeg tools with a privacy-neutral virtual prefix."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "8.1.2"
SOURCE_SHA256 = "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"
NEUTRAL_PREFIX = "/opt/larp-audio/ffmpeg"
CONFIGURE_FLAGS = (
    "--disable-gpl",
    "--disable-nonfree",
    "--disable-doc",
    "--disable-ffplay",
    "--disable-network",
    "--disable-autodetect",
    "--disable-shared",
    "--enable-static",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "resources/bin/macos-arm64")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("The checked-in macOS media tools must be built natively on macOS arm64.")
    archive = args.source_archive.resolve()
    if not archive.is_file() or sha256(archive) != SOURCE_SHA256:
        raise SystemExit("FFmpeg source archive is missing or does not match the pinned SHA-256.")
    with tempfile.TemporaryDirectory(prefix="larp-ffmpeg-build-") as temporary:
        build_root = Path(temporary)
        with tarfile.open(archive, "r:xz") as source:
            source.extractall(build_root, filter="data")
        source_root = build_root / f"ffmpeg-{VERSION}"
        configure = [str(source_root / "configure"), f"--prefix={NEUTRAL_PREFIX}", *CONFIGURE_FLAGS]
        subprocess.run(configure, cwd=source_root, check=True)
        subprocess.run(
            ["make", f"-j{max(1, os.cpu_count() or 1)}", "ffmpeg", "ffprobe"],
            cwd=source_root,
            check=True,
        )
        args.output.mkdir(parents=True, exist_ok=True)
        for name in ("ffmpeg", "ffprobe"):
            destination = args.output / name
            temporary_output = args.output / f".{name}.partial"
            shutil.copy2(source_root / name, temporary_output)
            temporary_output.chmod(0o755)
            os.replace(temporary_output, destination)
            print(f"{name} {sha256(destination)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
