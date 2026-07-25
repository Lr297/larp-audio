#!/usr/bin/env python3
"""Collect license files for the pinned Python runtime into app resources."""

from __future__ import annotations

import importlib.metadata
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "resources/licenses/python"
PACKAGES = (
    "PySide6", "shiboken6", "faster-whisper", "ctranslate2", "tokenizers",
    "av", "certifi", "huggingface-hub", "numpy", "onnxruntime", "PyYAML",
    "requests", "urllib3", "charset-normalizer", "idna", "tqdm", "flatbuffers",
    "protobuf", "sympy", "mpmath", "filelock", "fsspec", "packaging",
    "spacy", "en-core-web-sm", "thinc", "blis", "catalogue", "confection",
    "cymem", "murmurhash", "preshed", "srsly", "spacy-legacy",
    "spacy-loggers", "wasabi", "weasel", "smart-open", "pydantic",
    "pydantic-core", "Jinja2", "MarkupSafe", "typer", "rich",
    "cloudpathlib", "wrapt",
)


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    notices = ["# Python runtime third-party notices", ""]
    for name in PACKAGES:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        license_expression = distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "See packaged license file"
        notices.append(f"- {distribution.metadata['Name']} {distribution.version}: {license_expression}")
        candidates = []
        for item in distribution.files or ():
            basename = Path(str(item)).name.lower()
            if basename.startswith(("license", "copying", "notice")):
                located = distribution.locate_file(item)
                if located.is_file():
                    candidates.append(located)
        package_dir = DESTINATION / f"{distribution.metadata['Name']}-{distribution.version}"
        package_dir.mkdir(parents=True, exist_ok=True)
        for index, source in enumerate(candidates):
            suffix = source.suffix or ".txt"
            shutil.copy2(source, package_dir / f"LICENSE-{index + 1}{suffix}")
    (DESTINATION / "THIRD_PARTY_NOTICES.md").write_text("\n".join(notices) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
