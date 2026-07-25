#!/usr/bin/env python3
"""Create and deeply validate the Stage 14 source and user-test archives."""

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
FIXED_TIME = (2026, 7, 21, 16, 0, 0)
VERSION = "1.0.0-rc.9"

STAGE_FILES = (
    "AGENTS.md",
    "DEFINITION_OF_DONE.md",
    "PRODUCT_SPEC.md",
    "README.md",
    "RELEASE_NOTES_STAGE_14_RC.md",
    "RUN_APP.md",
    "STAGE_14_REPORT.md",
    "USER_TEST_CHECKLIST.md",
    "USER_TEST_INSTALL.md",
    "config.example.toml",
    "docs/END_USER_PACKAGING.md",
    "docs/EDITOR_EXPORT.md",
    "docs/MACOS_BUILD.md",
    "docs/PREVIEW_AND_DIAGNOSTICS.md",
    "docs/SUBTITLES.md",
    "docs/TEST_STRATEGY.md",
    "docs/adr/ADR-002-local-syntax-analyzer.md",
    "packaging/larp_audio_macos.spec",
    "packaging/larp_audio_windows.spec",
    "packaging/requirements-macos-arm64.txt",
    "pyproject.toml",
    "resources/icons/larp-audio.svg",
    "resources/icons/larp_audio.icns",
    "resources/icons/larp_audio.iconset/icon_16x16.png",
    "resources/icons/larp_audio.iconset/icon_16x16@2x.png",
    "resources/icons/larp_audio.iconset/icon_32x32.png",
    "resources/icons/larp_audio.iconset/icon_32x32@2x.png",
    "resources/icons/larp_audio.iconset/icon_128x128.png",
    "resources/icons/larp_audio.iconset/icon_128x128@2x.png",
    "resources/icons/larp_audio.iconset/icon_256x256.png",
    "resources/icons/larp_audio.iconset/icon_256x256@2x.png",
    "resources/icons/larp_audio.iconset/icon_512x512.png",
    "resources/icons/larp_audio.iconset/icon_512x512@2x.png",
    "resources/icons/larp_audio_master.png",
    "scripts/build_app_icon.py",
    "scripts/build_macos_app.py",
    "scripts/build_macos_dmg.py",
    "scripts/benchmark_subtitle_segmentation.py",
    "scripts/compare_stage_14_6_policies.py",
    "scripts/subtitle_quality_summary.py",
    "scripts/create_stage_14_archives.py",
    "scripts/collect_runtime_licenses.py",
    "scripts/release_hygiene.py",
    "scripts/verify_packaged_app.py",
    "src/larp_audio_mvp/__init__.py",
    "src/larp_audio_mvp/app/process_audio.py",
    "src/larp_audio_mvp/app/desktop.py",
    "src/larp_audio_mvp/app/generate_subtitles.py",
    "src/larp_audio_mvp/config/settings.py",
    "src/larp_audio_mvp/core/contracts.py",
    "src/larp_audio_mvp/core/errors.py",
    "src/larp_audio_mvp/exports/__init__.py",
    "src/larp_audio_mvp/exports/contracts.py",
    "src/larp_audio_mvp/exports/service.py",
    "src/larp_audio_mvp/exports/srt.py",
    "src/larp_audio_mvp/exports/validation.py",
    "src/larp_audio_mvp/gui/application.py",
    "src/larp_audio_mvp/gui/controller.py",
    "src/larp_audio_mvp/gui/design/stylesheet.py",
    "src/larp_audio_mvp/gui/design/widgets.py",
    "src/larp_audio_mvp/gui/motion.py",
    "src/larp_audio_mvp/gui/universal_export_dialog.py",
    "src/larp_audio_mvp/gui/main_window.py",
    "src/larp_audio_mvp/gui/models.py",
    "src/larp_audio_mvp/gui/preview/contracts.py",
    "src/larp_audio_mvp/gui/preview/synchronization.py",
    "src/larp_audio_mvp/gui/preview/widgets.py",
    "src/larp_audio_mvp/gui/production_workspace.py",
    "src/larp_audio_mvp/gui/speech_setup.py",
    "src/larp_audio_mvp/gui/workers.py",
    "src/larp_audio_mvp/pipeline/service.py",
    "src/larp_audio_mvp/runtime/migration.py",
    "src/larp_audio_mvp/subtitles/chunker.py",
    "src/larp_audio_mvp/subtitles/display.py",
    "src/larp_audio_mvp/subtitles/grammar.py",
    "src/larp_audio_mvp/subtitles/__init__.py",
    "src/larp_audio_mvp/subtitles/policy.py",
    "src/larp_audio_mvp/subtitles/repair.py",
    "src/larp_audio_mvp/subtitles/serialization.py",
    "src/larp_audio_mvp/subtitles/service.py",
    "src/larp_audio_mvp/subtitles/syntax.py",
    "src/larp_audio_mvp/subtitles/timing.py",
    "src/larp_audio_mvp/subtitles/validation.py",
    "src/larp_audio_mvp/subtitles/wrapping.py",
    "src/larp_audio_mvp/version.py",
    "tests/assets/stage14_rapid_voiceover_script.txt",
    "tests/assets/stage14_3_grammar_quality_script.txt",
    "tests/exports/__init__.py",
    "tests/exports/test_universal_export.py",
    "tests/gui/test_main_window.py",
    "tests/gui/test_preview.py",
    "tests/gui/test_state_and_model.py",
    "tests/gui/test_stage_12_1_redesign.py",
    "tests/gui/test_stage_14_1_polish.py",
    "tests/gui/test_stage_13_consumer_mode.py",
    "tests/integration/test_desktop_gui.py",
    "tests/integration/test_subtitle_generation.py",
    "tests/packaging/test_stage_14_release.py",
    "tests/pipeline/test_full_pipeline.py",
    "tests/subtitles/test_chunker.py",
    "tests/subtitles/test_semantic_phrase_policy.py",
    "tests/subtitles/test_scoring_corpus.py",
    "tests/subtitles/test_serialization_and_srt.py",
    "tests/subtitles/test_stage_14_2_policy.py",
    "tests/subtitles/test_stage_14_3_grammar.py",
    "tests/subtitles/test_stage_14_3_real_length.py",
    "tests/subtitles/test_stage_14_4_orphans_and_layout.py",
    "tests/subtitles/test_stage_14_5_syntax_engine.py",
    "tests/subtitles/test_stage_14_6_conservative_policy.py",
    "tests/test_config.py",
    "uv.lock",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_files(files: list[Path]) -> list[Path]:
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise SystemExit("Archive allowlist has missing files: " + ", ".join(missing))
    failures, _warnings = validate_public_files(ROOT, files)
    failures.extend(scan_files(ROOT, files))
    if failures:
        raise SystemExit("Source hygiene failed: " + "; ".join(failures[:10]))
    for path in files:
        result = scan_path(path)
        if not result.ok:
            raise SystemExit("Source privacy failed: " + "; ".join(result.failures))
    return files


def write_source_archive(destination: Path, files: list[Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(ROOT).as_posix()):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            archive.writestr(info, path.read_bytes())


def checksum_text(files: list[Path], *, base: Path | None = None) -> str:
    return "".join(
        f"{sha256(path)}  {os.path.relpath(path, base) if base is not None else path.name}\n"
        for path in files
    )


def write_handoff(destination: Path, payload_checksum: Path) -> None:
    members = (
        (DIST / f"LARP-Audio-{VERSION}-macOS-arm64.dmg", f"LARP-Audio-{VERSION}-macOS-arm64.dmg"),
        (DIST / f"LARP-Audio-{VERSION}-macOS-arm64.zip", f"LARP-Audio-{VERSION}-macOS-arm64.zip"),
        (payload_checksum, "SHA256SUMS.txt"),
        (ROOT / "USER_TEST_INSTALL.md", "USER_TEST_INSTALL.md"),
        (ROOT / "USER_TEST_CHECKLIST.md", "USER_TEST_CHECKLIST.md"),
        (ROOT / "RELEASE_NOTES_STAGE_14_RC.md", "RELEASE_NOTES_STAGE_14_RC.md"),
    )
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_STORED) as archive:
        for path, name in members:
            if not path.is_file():
                raise SystemExit(f"Handoff input is missing: {name}")
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def verify_zip(path: Path, expected_names: set[str] | None = None) -> int:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"Archive CRC failed for {path.name}: {bad}")
        names = {info.filename for info in archive.infolist()}
        if expected_names is not None and names != expected_names:
            raise SystemExit(f"Unexpected handoff members: {sorted(names)}")
        count = len(archive.infolist())
    result = scan_path(path)
    if not result.ok:
        raise SystemExit("Archive privacy failed: " + "; ".join(result.failures))
    return count


def main() -> int:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    stage_path = OUTPUTS / "stage_14_output.zip"
    full_path = OUTPUTS / "stage_14_full_project.zip"
    handoff_path = OUTPUTS / "stage_14_user_test_handoff.zip"

    stage_inputs = [ROOT / name for name in STAGE_FILES]
    stage_inputs.extend(
        path
        for path in sorted((ROOT / "resources/licenses/python").rglob("*"))
        if path.is_file()
    )
    stage = checked_files(stage_inputs)
    full = checked_files(collect_public_files(ROOT))
    write_source_archive(stage_path, stage)
    write_source_archive(full_path, full)
    stage_count = verify_zip(stage_path)
    full_count = verify_zip(full_path)

    dmg = DIST / f"LARP-Audio-{VERSION}-macOS-arm64.dmg"
    app_zip = DIST / f"LARP-Audio-{VERSION}-macOS-arm64.zip"
    payload_checksum = DIST / "SHA256SUMS.payload.txt"
    payload_checksum.write_text(checksum_text([dmg, app_zip]), encoding="utf-8")
    expected_handoff = {
        dmg.name,
        app_zip.name,
        "SHA256SUMS.txt",
        "USER_TEST_INSTALL.md",
        "USER_TEST_CHECKLIST.md",
        "RELEASE_NOTES_STAGE_14_RC.md",
    }
    write_handoff(handoff_path, payload_checksum)
    handoff_count = verify_zip(handoff_path, expected_handoff)
    payload_checksum.unlink()

    final_checksum = DIST / "SHA256SUMS.txt"
    final_files = [dmg, app_zip, stage_path, full_path, handoff_path]
    final_checksum.write_text(checksum_text(final_files, base=DIST), encoding="utf-8")
    checksum_scan = scan_path(final_checksum)
    if not checksum_scan.ok:
        raise SystemExit("Final checksum privacy validation failed")

    print(f"{stage_path.name}: {stage_count} files")
    print(f"{full_path.name}: {full_count} files")
    print(f"{handoff_path.name}: {handoff_count} files")
    print(final_checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
