#!/usr/bin/env python3
"""Create deterministic Stage 13.1 delta and allowlisted full-source archives."""

from __future__ import annotations

import zipfile
from pathlib import Path

from release_hygiene import collect_public_files, scan_files, scan_zip_bytes, validate_public_files

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
FIXED_TIME = (2026, 7, 20, 12, 0, 0)

STAGE_FILES = (
    ".gitignore",
    ".github/workflows/build-windows.yml",
    ".github/workflows/preflight.yml",
    "README.md",
    "RUN_APP.md",
    "STAGE_13_1_REPORT.md",
    "docs/CLEAN_MACHINE_TEST.md",
    "docs/END_USER_PACKAGING.md",
    "docs/INSTALL_STAGE_13_1.md",
    "docs/MACOS_BUILD.md",
    "docs/RELEASE_NOTES_STAGE_13_1.md",
    "docs/RELEASE_HYGIENE.md",
    "docs/SPEECH_ENGINE_MANAGEMENT.md",
    "scripts/build_macos_dmg.py",
    "scripts/check_public_repository.py",
    "scripts/create_stage_13_1_archives.py",
    "scripts/release_hygiene.py",
    "src/larp_audio_mvp/gui/main_window.py",
    "src/larp_audio_mvp/gui/speech_setup.py",
    "src/larp_audio_mvp/app/desktop.py",
    "src/larp_audio_mvp/speech_engine/manager.py",
    "tests/gui/test_speech_setup_lifecycle.py",
    "tests/packaging/test_release_hygiene.py",
    "tests/speech_engine/test_manager.py",
)


def write_archive(destination: Path, files: list[Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda value: value.relative_to(ROOT).as_posix()):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            archive.writestr(info, path.read_bytes())


def checked_files(files: list[Path]) -> list[Path]:
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"Archive allowlist contains missing files: {missing}")
    failures, _warnings = validate_public_files(ROOT, files)
    failures.extend(scan_files(ROOT, files))
    if failures:
        raise SystemExit("Archive preflight failed:\n" + "\n".join(failures))
    return files


def verify_archive(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"Archive CRC failed: {bad}")
        names = archive.namelist()
    findings = scan_zip_bytes(path.read_bytes(), path.name, root=ROOT)
    if findings:
        raise SystemExit("Archive privacy/hygiene scan failed:\n" + "\n".join(findings))
    return len(names)


def main() -> int:
    stage = checked_files([ROOT / name for name in STAGE_FILES])
    full = checked_files(collect_public_files(ROOT))
    stage_path = OUTPUTS / "stage_13_1_output.zip"
    full_path = OUTPUTS / "stage_13_1_full_project.zip"
    write_archive(stage_path, stage)
    write_archive(full_path, full)
    print(f"{stage_path}: {verify_archive(stage_path)} files")
    print(f"{full_path}: {verify_archive(full_path)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
