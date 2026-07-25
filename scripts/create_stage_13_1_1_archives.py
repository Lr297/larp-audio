#!/usr/bin/env python3
"""Create and deeply validate the Stage 13.1.1 release archives."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

from release_hygiene import collect_public_files, scan_files, validate_public_files
from scan_release_privacy import scan_path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DIST = ROOT / "dist"
FIXED_TIME = (2026, 7, 21, 12, 0, 0)

STAGE_FILES = (
    "INSTALL_STAGE_13_1_1.md",
    "RELEASE_NOTES_STAGE_13_1_1.md",
    "STAGE_13_1_1_REPORT.md",
    "docs/BUNDLED_FFMPEG.md",
    "docs/END_USER_PACKAGING.md",
    "docs/MACOS_BUILD.md",
    "docs/PACKAGED_ARTIFACT_PRIVACY.md",
    "docs/RELEASE_HYGIENE.md",
    "packaging/larp_audio_macos.spec",
    "packaging/requirements-macos-arm64.txt",
    "resources/bin/macos-arm64/ffmpeg",
    "resources/bin/macos-arm64/ffprobe",
    "resources/bin/manifest.json",
    "scripts/README.md",
    "scripts/build_ffmpeg_macos.py",
    "scripts/build_macos_app.py",
    "scripts/build_macos_dmg.py",
    "scripts/check_public_repository.py",
    "scripts/create_stage_13_1_1_archives.py",
    "scripts/release_hygiene.py",
    "scripts/scan_release_privacy.py",
    "tests/packaging/test_artifact_privacy.py",
    "tests/packaging/test_packaging.py",
    "tests/packaging/test_release_hygiene.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_files(files: list[Path]) -> list[Path]:
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"Archive allowlist contains {len(missing)} missing files")
    failures, _warnings = validate_public_files(ROOT, files)
    failures.extend(scan_files(ROOT, files))
    if failures:
        raise SystemExit("Source archive hygiene preflight failed: " + "; ".join(failures[:10]))
    for path in files:
        result = scan_path(path)
        if not result.ok:
            raise SystemExit("Source privacy preflight failed: " + "; ".join(result.failures))
    return files


def write_source_archive(destination: Path, files: list[Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda value: value.relative_to(ROOT).as_posix()):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            archive.writestr(info, path.read_bytes())


def write_handoff(destination: Path, payload_checksum: Path) -> None:
    members = (
        (DIST / "LARP-Audio-macOS-arm64.dmg", "LARP-Audio-macOS-arm64.dmg"),
        (DIST / "LARP-Audio-macOS-arm64.zip", "LARP-Audio-macOS-arm64.zip"),
        (payload_checksum, "SHA256SUMS.txt"),
        (ROOT / "RELEASE_NOTES_STAGE_13_1_1.md", "RELEASE_NOTES_STAGE_13_1_1.md"),
        (ROOT / "INSTALL_STAGE_13_1_1.md", "INSTALL_STAGE_13_1_1.md"),
    )
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_STORED) as archive:
        for path, name in members:
            if not path.is_file():
                raise SystemExit(f"Release handoff input is missing: {name}")
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def verify_zip(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"Archive CRC failed for {path.name}")
        count = len(archive.infolist())
    result = scan_path(path)
    if not result.ok:
        raise SystemExit("Artifact privacy scan failed: " + "; ".join(result.failures))
    return count


def checksum_text(files: list[Path], *, base: Path | None = None) -> str:
    return "".join(
        f"{sha256(path)}  {os.path.relpath(path, base) if base is not None else path.name}\n"
        for path in files
    )


def main() -> int:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    stage_path = OUTPUTS / "stage_13_1_1_output.zip"
    full_path = OUTPUTS / "stage_13_1_1_full_project.zip"
    handoff_path = OUTPUTS / "stage_13_1_1_release_handoff.zip"
    stage = checked_files([ROOT / name for name in STAGE_FILES])
    full = checked_files(collect_public_files(ROOT))
    write_source_archive(stage_path, stage)
    write_source_archive(full_path, full)
    stage_count = verify_zip(stage_path)
    full_count = verify_zip(full_path)

    app_zip = DIST / "LARP-Audio-macOS-arm64.zip"
    dmg = DIST / "LARP-Audio-macOS-arm64.dmg"
    payload_checksum = DIST / "SHA256SUMS.payload.txt"
    payload_checksum.write_text(checksum_text([dmg, app_zip]), encoding="utf-8")
    write_handoff(handoff_path, payload_checksum)
    handoff_count = verify_zip(handoff_path)
    payload_checksum.unlink()

    final_checksum = DIST / "SHA256SUMS.txt"
    final_files = [dmg, app_zip, stage_path, full_path, handoff_path]
    final_checksum.write_text(checksum_text(final_files, base=DIST), encoding="utf-8")
    if not scan_path(final_checksum).ok:
        raise SystemExit("Final checksum file failed privacy validation")
    print(f"{stage_path.name}: {stage_count} files")
    print(f"{full_path.name}: {full_count} files")
    print(f"{handoff_path.name}: {handoff_count} files")
    print(final_checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
