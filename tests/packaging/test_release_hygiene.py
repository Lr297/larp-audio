from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_hygiene():
    spec = importlib.util.spec_from_file_location("release_hygiene", ROOT / "scripts/release_hygiene.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_generated_and_model_patterns_are_ignored() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("models/", "model.bin", "outputs/", "dist/", "*.partial", ".cache/", "*.lock", "!uv.lock"):
        assert pattern in text
    assert "src/" not in text and "tests/" not in text


def test_public_allowlist_excludes_local_models_outputs_and_history() -> None:
    hygiene = load_hygiene()
    names = {path.relative_to(ROOT).as_posix() for path in hygiene.collect_public_files(ROOT)}
    assert not any(name.startswith("models/") for name in names)
    assert not any(name.startswith("outputs/") for name in names)
    assert "STAGE_13_REPORT.md" not in names
    assert "src/larp_audio_mvp/models/faster_whisper.py" in names


def test_nested_zip_privacy_and_model_detection(tmp_path: Path) -> None:
    hygiene = load_hygiene()
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("models/engine/model.bin", b"x")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("nested.zip", inner.read_bytes())
    findings = hygiene.scan_zip_bytes(outer.read_bytes(), "outer.zip")
    assert any("model" in finding for finding in findings)


def test_privacy_scan_detects_private_and_repository_markers() -> None:
    hygiene = load_hygiene()
    private_marker = ("/" + "Users" + "/" + "roman" + "lucenko" + "/file").encode()
    repository_marker = str(ROOT).encode()
    assert hygiene.scan_text("a", private_marker)
    assert hygiene.scan_text("b", repository_marker, root=ROOT)


def test_public_repository_preflight_passes_current_allowlist() -> None:
    hygiene = load_hygiene()
    files = hygiene.collect_public_files(ROOT)
    failures, _warnings = hygiene.validate_public_files(ROOT, files)
    assert not failures
    assert not hygiene.scan_files(ROOT, files)
