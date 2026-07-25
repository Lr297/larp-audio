#!/usr/bin/env python3
"""Create deterministic Stage 13 source archives without models or caches."""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

STAGE_FILES = (
    ".github/workflows/build-windows.yml", "README.md", "RUN_APP.md", "STAGE_13_REPORT.md",
    "pyproject.toml", "uv.lock",
    "docs/BUNDLED_FFMPEG.md", "docs/CLEAN_MACHINE_TEST.md", "docs/DESKTOP_GUI.md",
    "docs/END_USER_PACKAGING.md", "docs/MACOS_BUILD.md", "docs/SPEECH_ENGINE_MANAGEMENT.md", "docs/WINDOWS_BUILD.md",
    "packaging/larp_audio_macos.spec", "packaging/larp_audio_windows.spec", "packaging/offline-engine.json",
    "resources/bin/manifest.json", "resources/bin/macos-arm64/ffmpeg", "resources/bin/macos-arm64/ffprobe",
    "resources/bin/windows-x86_64/README.md", "resources/icons/LARP-Audio.icns", "resources/icons/larp-audio.svg",
    "scripts/build_app_icon.py", "scripts/build_macos_app.py", "scripts/build_macos_dmg.py", "scripts/build_windows.ps1",
    "scripts/collect_runtime_licenses.py", "scripts/create_stage_13_archives.py", "scripts/run_clean_machine_test.py",
    "scripts/run_windows_clean_machine_test.ps1", "scripts/verify_packaged_app.py",
    "src/larp_audio_mvp/app/desktop.py", "src/larp_audio_mvp/audio/executables.py",
    "src/larp_audio_mvp/gui/application.py", "src/larp_audio_mvp/gui/main_window.py", "src/larp_audio_mvp/gui/platform_paths.py",
    "src/larp_audio_mvp/gui/production_workspace.py", "src/larp_audio_mvp/gui/speech_setup.py",
    "src/larp_audio_mvp/pipeline/factory.py", "src/larp_audio_mvp/runtime/__init__.py", "src/larp_audio_mvp/runtime/migration.py",
    "src/larp_audio_mvp/runtime/paths.py", "src/larp_audio_mvp/runtime/resources.py",
    "src/larp_audio_mvp/speech_engine/__init__.py", "src/larp_audio_mvp/speech_engine/contracts.py",
    "src/larp_audio_mvp/speech_engine/definition.py", "src/larp_audio_mvp/speech_engine/errors.py", "src/larp_audio_mvp/speech_engine/manager.py",
    "tests/assets/stage13_synthetic_tone.wav", "tests/gui/test_main_window.py", "tests/gui/test_platform_paths.py",
    "tests/gui/test_stage_11.py", "tests/gui/test_stage_13_consumer_mode.py", "tests/packaging/test_packaging.py", "tests/runtime/test_migration.py",
    "tests/runtime/test_resources.py", "tests/speech_engine/test_manager.py",
)

EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "outputs", "work", "reference"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".partial"}
EXCLUDED_NAMES = {".DS_Store"}


def _write(archive: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(files, key=lambda value: value.as_posix()):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, (2026, 7, 20, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            output.writestr(info, path.read_bytes())


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    stage = [ROOT / value for value in STAGE_FILES]
    stage.extend(path for path in (ROOT / "resources/licenses").rglob("*") if path.is_file())
    missing = [str(path.relative_to(ROOT)) for path in stage if not path.is_file()]
    if missing:
        raise SystemExit(f"Stage file list contains missing files: {missing}")
    _write(OUTPUTS / "stage_13_output.zip", stage)
    full = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name in EXCLUDED_NAMES:
            continue
        if path.suffix in EXCLUDED_SUFFIXES or path.name.endswith(".partial.json"):
            continue
        # Production engines live outside source; guard against accidental inclusion.
        if path.name == "model.bin" and "faster-whisper-small" in relative.parts:
            continue
        full.append(path)
    _write(OUTPUTS / "stage_13_full_project.zip", full)
    for archive in (OUTPUTS / "stage_13_output.zip", OUTPUTS / "stage_13_full_project.zip"):
        with zipfile.ZipFile(archive) as value:
            bad = value.testzip()
            if bad is not None:
                raise SystemExit(f"Corrupt archive entry: {bad}")
            print(f"{archive}: {len(value.namelist())} files")


if __name__ == "__main__":
    main()
