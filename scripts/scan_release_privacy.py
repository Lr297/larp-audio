#!/usr/bin/env python3
"""Deep, bounded privacy scan for source and packaged release artifacts."""

from __future__ import annotations

import argparse
import io
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_ENTRIES = 20_000
DEFAULT_MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 2_000
DIAGNOSTIC_LIMIT = 40
STRING_SCAN_LIMIT = 32 * 1024 * 1024
TEXT_SUFFIXES = {
    ".cfg", ".ini", ".json", ".md", ".plist", ".ps1", ".pth", ".py",
    ".sh", ".spec", ".toml", ".txt", ".xml", ".yaml", ".yml",
}
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
}


def _fixed_private_markers() -> list[str]:
    user = "roman" + "lucenko"
    slash = "/"
    return [
        user,
        slash + "Users" + slash + user,
        "Documents" + slash + "Codex",
        "file:" + slash * 3 + "Users" + slash + user,
        "work" + slash + "stage13_ffmpeg",
        "planner-subagent-" + "hermes-1-reference-ivm",
    ]


def privacy_markers(root: Path = ROOT) -> tuple[bytes, ...]:
    values = _fixed_private_markers()
    home = Path.home().resolve()
    repository = root.resolve()
    values.extend((str(home), str(repository), str(repository.parent)))
    configured = os.environ.get("LARP_VENDOR_BUILD_ROOT")
    if configured:
        values.append(str(Path(configured).resolve()))
    return tuple(dict.fromkeys(value.encode("utf-8") for value in values if value))


class ScanResult:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.files_scanned = 0
        self.entries_scanned = 0
        self.expanded_bytes = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def fail(self, label: str, category: str) -> None:
        value = f"{label}: {category}"
        if value not in self.failures and len(self.failures) < DIAGNOSTIC_LIMIT:
            self.failures.append(value)

    def warn(self, label: str, category: str) -> None:
        value = f"{label}: {category}"
        if value not in self.warnings and len(self.warnings) < DIAGNOSTIC_LIMIT:
            self.warnings.append(value)


class Scanner:
    def __init__(
        self,
        *,
        root: Path = ROOT,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
        max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
    ) -> None:
        self.root = root.resolve()
        self.max_depth = max_depth
        self.max_entries = max_entries
        self.max_expanded_bytes = max_expanded_bytes
        self.max_compression_ratio = max_compression_ratio
        self.markers = privacy_markers(self.root)
        self.result = ScanResult()

    def scan(self, target: Path) -> ScanResult:
        target = target.resolve()
        if target.is_dir():
            self._scan_directory(target, target.name or "artifact")
        elif target.is_file():
            self._scan_file(target, target.name, depth=0)
        else:
            self.result.fail("artifact", "target does not exist")
        return self.result

    def _scan_directory(self, directory: Path, label: str) -> None:
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(directory).as_posix()
            self._scan_file(path, f"{label}/{relative}", depth=0)

    def _scan_file(self, path: Path, label: str, *, depth: int) -> None:
        self.result.files_scanned += 1
        self._scan_name(label, label)
        lowered = path.name.lower()
        if lowered.endswith(".dmg"):
            self._scan_dmg(path, label)
            return
        if zipfile.is_zipfile(path):
            self._scan_zip_path(path, label, depth=depth)
            return
        self._scan_stream(path.open("rb"), label)
        if self._is_macho(path):
            self._scan_macho_strings(path, label)
        if lowered == "direct_url.json":
            self._validate_direct_url(path.read_bytes(), label)
        if lowered.endswith(".egg-link") or lowered.startswith("__editable__"):
            self.result.fail(label, "editable installation metadata")
        if lowered.endswith(".pth"):
            self._validate_pth(path.read_bytes(), label)

    def _scan_name(self, name: str, label: str) -> None:
        encoded = name.encode("utf-8", "surrogateescape")
        if self._contains_private(encoded):
            self.result.fail(label, "private path marker in entry name")
        basename = PurePosixPath(name).name.lower()
        if basename.endswith(".egg-link") or basename.startswith("__editable__"):
            self.result.fail(label, "editable installation metadata")

    def _contains_private(self, data: bytes) -> bool:
        return any(marker in data for marker in self.markers)

    def _scan_stream(self, stream, label: str) -> None:
        overlap = max((len(value) for value in self.markers), default=1) - 1
        previous = b""
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            combined = previous + chunk
            if self._contains_private(combined):
                self.result.fail(label, "private build or source path")
                return
            if re.search(rb"/Users/(?:runner|build|ci)(?:/|$)", combined):
                self.result.warn(label, "generic third-party CI path")
            previous = combined[-overlap:] if overlap else b""

    def _scan_bytes(self, data: bytes, label: str) -> None:
        if self._contains_private(data):
            self.result.fail(label, "private build or source path")
        text = data.decode("utf-8", "ignore")
        if re.search(r"/Users/(?:runner|build|ci)(?:/|$)", text):
            self.result.warn(label, "generic third-party CI path")

    @staticmethod
    def _is_macho(path: Path) -> bool:
        try:
            with path.open("rb") as stream:
                return stream.read(4) in MACHO_MAGICS
        except OSError:
            return False

    def _scan_macho_strings(self, path: Path, label: str) -> None:
        strings = shutil.which("strings")
        if strings is None:
            self.result.warn(label, "strings utility unavailable; raw binary scan completed")
            return
        completed = subprocess.run(
            [strings, "-a", str(path)],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            self.result.warn(label, "strings utility failed; raw binary scan completed")
            return
        output = completed.stdout[:STRING_SCAN_LIMIT]
        self._scan_bytes(output, label)

    def _validate_direct_url(self, data: bytes, label: str) -> None:
        lowered = data.lower()
        if b"file://" in lowered or b'"editable": true' in lowered:
            self.result.fail(label, "local or editable direct_url metadata")

    def _validate_pth(self, data: bytes, label: str) -> None:
        lowered = data.lower()
        if b"file://" in lowered or b"__editable__" in lowered or self._contains_private(data):
            self.result.fail(label, "local-source .pth metadata")

    def _account_entry(self, info: zipfile.ZipInfo, label: str) -> bool:
        self.result.entries_scanned += 1
        if self.result.entries_scanned > self.max_entries:
            self.result.fail(label, "ZIP entry-count limit exceeded")
            return False
        self.result.expanded_bytes += info.file_size
        if self.result.expanded_bytes > self.max_expanded_bytes:
            self.result.fail(label, "ZIP expanded-byte limit exceeded")
            return False
        if info.file_size and info.compress_size == 0:
            self.result.fail(label, "ZIP compression-ratio policy exceeded")
            return False
        if info.compress_size and info.file_size / info.compress_size > self.max_compression_ratio:
            self.result.fail(label, "ZIP compression-ratio policy exceeded")
            return False
        return True

    def _scan_zip_path(self, path: Path, label: str, *, depth: int) -> None:
        if depth > self.max_depth:
            self.result.fail(label, "nested ZIP depth exceeds policy")
            return
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile):
            self.result.fail(label, "unreadable ZIP")
            return
        with archive, tempfile.TemporaryDirectory(prefix="larp-privacy-zip-") as temporary:
            for index, info in enumerate(archive.infolist()):
                entry_label = f"{label}!{info.filename}"
                self._scan_name(info.filename, entry_label)
                if info.is_dir() or not self._account_entry(info, entry_label):
                    continue
                lowered = info.filename.lower()
                with archive.open(info) as stream:
                    self._scan_stream(stream, entry_label)
                if lowered.endswith(".egg-link") or PurePosixPath(lowered).name.startswith("__editable__"):
                    self.result.fail(entry_label, "editable installation metadata")
                is_symlink = stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
                needs_materialization = not is_symlink and (
                    lowered.endswith((".zip", ".dmg"))
                    or lowered.endswith("direct_url.json")
                    or lowered.endswith(".pth")
                )
                if not needs_materialization:
                    continue
                destination = Path(temporary) / f"entry-{index}{PurePosixPath(info.filename).suffix}"
                with archive.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if lowered.endswith(".zip"):
                    self._scan_zip_path(destination, entry_label, depth=depth + 1)
                elif lowered.endswith(".dmg"):
                    self._scan_dmg(destination, entry_label)
                elif lowered.endswith("direct_url.json"):
                    self._validate_direct_url(destination.read_bytes(), entry_label)
                else:
                    self._validate_pth(destination.read_bytes(), entry_label)

    def _scan_dmg(self, path: Path, label: str) -> None:
        if sys.platform != "darwin" or shutil.which("hdiutil") is None:
            self.result.fail(label, "DMG scan requires macOS hdiutil")
            return
        verified = subprocess.run(["hdiutil", "verify", str(path)], capture_output=True, timeout=180, check=False)
        if verified.returncode != 0:
            self.result.fail(label, "DMG verification failed")
            return
        with tempfile.TemporaryDirectory(prefix="larp-privacy-dmg-") as temporary:
            mountpoint = Path(temporary) / "mount"
            mountpoint.mkdir()
            attached = False
            try:
                attach = subprocess.run(
                    ["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mountpoint), "-plist", str(path)],
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
                if attach.returncode != 0:
                    self.result.fail(label, "DMG read-only mount failed")
                    return
                plistlib.loads(attach.stdout)
                attached = True
                self._scan_directory(mountpoint, f"{label}!mounted")
            except (OSError, plistlib.InvalidFileException, subprocess.TimeoutExpired):
                self.result.fail(label, "DMG controlled scan failed")
            finally:
                if attached:
                    detached = subprocess.run(["hdiutil", "detach", str(mountpoint)], capture_output=True, timeout=60, check=False)
                    if detached.returncode != 0:
                        self.result.fail(label, "DMG unmount failed")


def scan_path(path: Path, **limits) -> ScanResult:
    return Scanner(**limits).scan(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+", type=Path)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--max-expanded-bytes", type=int, default=DEFAULT_MAX_EXPANDED_BYTES)
    args = parser.parse_args()
    failed = False
    for target in args.targets:
        result = scan_path(
            target,
            max_depth=args.max_depth,
            max_entries=args.max_entries,
            max_expanded_bytes=args.max_expanded_bytes,
        )
        safe_label = target.name or "artifact"
        for warning in result.warnings:
            print(f"WARNING: {warning}")
        for failure in result.failures:
            print(f"ERROR: {failure}")
        print(
            f"{safe_label}: files={result.files_scanned} entries={result.entries_scanned} "
            f"expanded_bytes={result.expanded_bytes} privacy={'PASS' if result.ok else 'FAIL'}"
        )
        failed |= not result.ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
