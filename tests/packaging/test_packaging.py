from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    return value


def test_specs_include_required_native_stacks_and_resources() -> None:
    mac = (ROOT / "packaging/larp_audio_macos.spec").read_text()
    for value in ("faster_whisper", "ctranslate2", "tokenizers", "av", "QtMultimedia", "bin/macos-arm64"):
        assert value in mac
    windows = (ROOT / "packaging/larp_audio_windows.spec").read_text()
    assert "windows-x86_64" in windows and "console=False" in windows


@pytest.mark.integration
def test_bundled_macos_media_matches_manifest_and_executes() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("checked resource is macOS arm64")
    manifest = json.loads((ROOT / "resources/bin/manifest.json").read_text())
    values = manifest["platforms"]["macos-arm64"]
    for name in ("ffmpeg", "ffprobe"):
        path = ROOT / "resources/bin/macos-arm64" / name
        assert _sha(path) == values[f"{name}_sha256"]
        completed = subprocess.run([str(path), "-version"], capture_output=True, text=True, timeout=10, env={"PATH": ""})
        assert completed.returncode == 0
        assert "8.1.2" in completed.stdout.splitlines()[0]


@pytest.mark.integration
def test_bundled_macos_media_has_neutral_build_provenance() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        pytest.skip("checked resource is macOS arm64")
    manifest = json.loads((ROOT / "resources/bin/manifest.json").read_text())
    assert manifest["build_provenance"]["virtual_prefix"] == "/opt/larp-audio/ffmpeg"
    private_markers = [
        ("roman" + "lucenko").encode(),
        ("Documents" + "/" + "Codex").encode(),
        str(ROOT).encode(),
        str(Path.home()).encode(),
        ("work" + "/" + "stage13_ffmpeg").encode(),
    ]
    for name in ("ffmpeg", "ffprobe"):
        path = ROOT / "resources/bin/macos-arm64" / name
        assert os.access(path, os.X_OK)
        output = subprocess.run(["strings", "-a", str(path)], capture_output=True, check=True).stdout
        assert b"--prefix=/opt/larp-audio/ffmpeg" in output
        assert not any(marker in output for marker in private_markers)
        assert "arm64" in subprocess.run(["file", str(path)], capture_output=True, text=True, check=True).stdout


def test_production_model_is_not_stored_in_source_archives() -> None:
    assert not (ROOT / "models/faster-whisper-small").exists()
    definition = (ROOT / "src/larp_audio_mvp/speech_engine/definition.py").read_text()
    assert "2ec96c5472da50d38d40c0cfe0602af2e94b4c8a" in definition
