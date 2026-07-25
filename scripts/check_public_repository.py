#!/usr/bin/env python3
"""Fail when the intended public source snapshot violates release hygiene."""

from __future__ import annotations

import argparse
from pathlib import Path

from release_hygiene import collect_public_files, scan_files, validate_public_files
from scan_release_privacy import Scanner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.snapshot.resolve()
    files = collect_public_files(root)
    failures, warnings = validate_public_files(root, files)
    failures.extend(scan_files(root, files))
    privacy = Scanner(root=root)
    for path in files:
        privacy._scan_file(path, path.relative_to(root).as_posix(), depth=0)
    failures.extend(privacy.result.failures)
    warnings.extend(privacy.result.warnings)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for failure in failures:
        print(f"ERROR: {failure}")
    print(f"Checked {len(files)} public snapshot files")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
