#!/usr/bin/env python3
"""Shared allowlist and bounded privacy checks for public release snapshots."""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

PUBLIC_DIRECTORIES = ("src", "tests", "docs", "scripts", "packaging", "resources", ".github")
PUBLIC_ROOT_FILES = (
    ".gitignore",
    ".python-version",
    "AGENTS.md",
    "PRODUCT_SPEC.md",
    "DEFINITION_OF_DONE.md",
    "README.md",
    "RUN_APP.md",
    "STAGE_14_REPORT.md",
    "RELEASE_NOTES_STAGE_14_RC.md",
    "USER_TEST_INSTALL.md",
    "USER_TEST_CHECKLIST.md",
    "config.example.toml",
    "pyproject.toml",
    "uv.lock",
)
TEXT_SUFFIXES = {
    ".cfg", ".ini", ".json", ".log", ".md", ".ps1", ".py", ".sh",
    ".spec", ".toml", ".txt", ".xml", ".yaml", ".yml",
}
FORBIDDEN_PARTS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".cache", "build",
    "dist", "outputs", "output", "work", "reference",
    "application-data", "local-app-data", "speech-engines",
}
FORBIDDEN_SUFFIXES = (".partial", ".partial.json", ".dmg", ".app")
RAW_AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
ALLOWED_AUDIO = {"tests/assets/stage13_synthetic_tone.wav"}
ALLOWED_LARGE = {
    "resources/bin/macos-arm64/ffmpeg",
    "resources/bin/macos-arm64/ffprobe",
}
WARNING_SIZE = 10 * 1024 * 1024
FAILURE_SIZE = 50 * 1024 * 1024


def collect_public_files(root: Path) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []
    for name in PUBLIC_ROOT_FILES:
        candidate = root / name
        if candidate.is_file():
            files.append(candidate)
    for directory in PUBLIC_DIRECTORIES:
        base = root / directory
        if base.is_dir():
            files.extend(
                path for path in base.rglob("*")
                if path.is_file()
                and not any(part in {"__pycache__", ".pytest_cache", ".cache"} for part in path.relative_to(root).parts)
                and path.suffix.lower() not in {".pyc", ".pyo"}
            )
    return sorted(set(files))


def forbidden_reason(relative: str) -> str | None:
    path = Path(relative)
    parts = set(path.parts)
    if parts & FORBIDDEN_PARTS:
        return "forbidden generated/private directory"
    if path.parts and path.parts[0] == "models":
        return "production/local model directory"
    lowered = path.name.lower()
    if lowered == "model.bin":
        return "production model file"
    if lowered.endswith(FORBIDDEN_SUFFIXES):
        return "partial/application/release binary"
    if lowered.endswith(".lock") and relative != "uv.lock":
        return "runtime lock file"
    if lowered.endswith(".zip"):
        return "nested or previous release archive"
    if path.suffix.lower() in RAW_AUDIO_SUFFIXES and relative not in ALLOWED_AUDIO:
        return "unapproved raw audio"
    return None


def validate_public_files(root: Path, files: list[Path]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        reason = forbidden_reason(relative)
        if reason:
            failures.append(f"{relative}: {reason}")
        size = path.stat().st_size
        if size > FAILURE_SIZE and relative not in ALLOWED_LARGE:
            failures.append(f"{relative}: unexpected file exceeds 50 MiB")
        elif size > WARNING_SIZE:
            if relative in ALLOWED_LARGE:
                warnings.append(f"{relative}: documented LGPL FFmpeg vendor binary")
            else:
                warnings.append(f"{relative}: file exceeds 10 MiB")
    return failures, warnings


def _privacy_needles(root: Path | None = None) -> tuple[str, ...]:
    slash = "/"
    backslash = "\\"
    values = [
        "roman" + "lucenko",
        "Documents" + slash + "Codex",
        "file:" + slash * 3 + "Users" + slash + "roman" + "lucenko",
    ]
    if root is not None:
        values.append(str(root.resolve()))
    home = Path.home()
    if home != Path(slash):
        values.append(str(home))
    temporary_root = os.environ.get("TMPDIR")
    if temporary_root:
        values.append(str(Path(temporary_root).resolve()))
    return tuple(dict.fromkeys(value for value in values if value))


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"hf_[A-Za-z0-9]{24,}"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
)


def scan_text(label: str, data: bytes, *, root: Path | None = None) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    findings = [f"{label}: contains private path marker" for value in _privacy_needles(root) if value in text]
    findings.extend(f"{label}: contains secret-like material" for pattern in SECRET_PATTERNS if pattern.search(text))
    return findings


def scan_zip_bytes(data: bytes, label: str, *, root: Path | None = None, depth: int = 0) -> list[str]:
    if depth > 2:
        return [f"{label}: nested ZIP depth exceeds policy"]
    findings: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile):
        return [f"{label}: unreadable ZIP"]
    with archive:
        if archive.testzip() is not None:
            findings.append(f"{label}: CRC failure")
        for info in archive.infolist():
            name = info.filename
            reason = forbidden_reason(name)
            if reason:
                findings.append(f"{label}!{name}: {reason}")
            findings.extend(scan_text(f"{label}!{name} [name]", name.encode(), root=root))
            if info.is_dir() or info.file_size > FAILURE_SIZE:
                continue
            payload = archive.read(info)
            if name.lower().endswith(".zip"):
                findings.extend(scan_zip_bytes(payload, f"{label}!{name}", root=root, depth=depth + 1))
            elif Path(name).suffix.lower() in TEXT_SUFFIXES or Path(name).name in {"LICENSE", "NOTICE"}:
                findings.extend(scan_text(f"{label}!{name}", payload, root=root))
    return findings


def scan_files(root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == ".zip":
            findings.extend(scan_zip_bytes(path.read_bytes(), relative, root=root))
        elif path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", "NOTICE"}:
            findings.extend(scan_text(relative, path.read_bytes(), root=root))
    return findings
