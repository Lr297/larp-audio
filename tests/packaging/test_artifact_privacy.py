from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_scanner():
    spec = importlib.util.spec_from_file_location("scan_release_privacy", ROOT / "scripts/scan_release_privacy.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_home() -> str:
    return "/" + "Users" + "/" + "roman" + "lucenko"


def test_clean_text_and_remote_direct_url_pass(tmp_path: Path) -> None:
    scanner = load_scanner()
    (tmp_path / "README.md").write_text("A clean release file.\n")
    metadata = tmp_path / "direct_url.json"
    metadata.write_text(json.dumps({"url": "https://packages.example.invalid/project.whl"}))
    result = scanner.scan_path(tmp_path)
    assert result.ok


@pytest.mark.parametrize("suffix", [".txt", ".json", ".plist", ".bin"])
def test_private_markers_fail_in_text_metadata_and_binary(tmp_path: Path, suffix: str) -> None:
    scanner = load_scanner()
    marker = private_home() if suffix != ".plist" else str(ROOT)
    (tmp_path / f"leak{suffix}").write_bytes(b"prefix\x00" + marker.encode() + b"\x00suffix")
    result = scanner.scan_path(tmp_path)
    assert not result.ok
    assert all(private_home() not in message and str(ROOT) not in message for message in result.failures)


def test_neutral_ffmpeg_prefix_passes_and_old_vendor_prefix_fails(tmp_path: Path) -> None:
    scanner = load_scanner()
    neutral = tmp_path / "neutral.bin"
    neutral.write_bytes(b"--prefix=/opt/larp-audio/ffmpeg")
    assert scanner.scan_path(neutral).ok
    old = tmp_path / "old.bin"
    old.write_bytes(("--prefix=/tmp/" + "work/stage13_" + "ffmpeg/install").encode())
    assert not scanner.scan_path(old).ok


def test_clean_zip_and_leak_inside_zip(tmp_path: Path) -> None:
    scanner = load_scanner()
    clean = tmp_path / "clean.zip"
    with zipfile.ZipFile(clean, "w") as archive:
        archive.writestr("notes.txt", "clean")
    assert scanner.scan_path(clean).ok
    leaking = tmp_path / "leaking.zip"
    with zipfile.ZipFile(leaking, "w") as archive:
        archive.writestr("metadata.json", json.dumps({"home": private_home()}))
    assert not scanner.scan_path(leaking).ok


def test_nested_and_large_outer_zip_are_scanned(tmp_path: Path) -> None:
    scanner = load_scanner()
    inner_data = io.BytesIO()
    with zipfile.ZipFile(inner_data, "w") as inner:
        inner.writestr("small.json", json.dumps({"source": private_home()}))
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("padding.bin", b"x" * (2 * 1024 * 1024))
        archive.writestr("nested.zip", inner_data.getvalue())
    assert not scanner.scan_path(outer).ok


def test_recursion_depth_and_zip_bomb_limits_are_controlled(tmp_path: Path) -> None:
    scanner = load_scanner()
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("leaf.txt", "clean")
    for level in range(3):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr(f"level-{level}.zip", payload.getvalue())
        payload = nested
    deep = tmp_path / "deep.zip"
    deep.write_bytes(payload.getvalue())
    assert not scanner.scan_path(deep, max_depth=1).ok

    compressed = tmp_path / "ratio.zip"
    with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"0" * 200_000)
    assert not scanner.Scanner(max_compression_ratio=2).scan(compressed).ok


def test_editable_metadata_is_rejected(tmp_path: Path) -> None:
    scanner = load_scanner()
    direct = tmp_path / "direct_url.json"
    direct.write_text(json.dumps({"url": "file:" + "///" + private_home() + "/checkout", "dir_info": {"editable": True}}))
    assert not scanner.scan_path(tmp_path).ok
    direct.unlink()
    (tmp_path / "project.egg-link").write_text("relative/source")
    assert not scanner.scan_path(tmp_path).ok
    (tmp_path / "project.egg-link").unlink()
    (tmp_path / "__editable___project_finder.py").write_text("pass")
    assert not scanner.scan_path(tmp_path).ok
    (tmp_path / "__editable___project_finder.py").unlink()
    (tmp_path / "project.pth").write_text("import __editable___project_finder")
    assert not scanner.scan_path(tmp_path).ok


def test_generic_ci_path_is_warning_but_exact_private_path_fails(tmp_path: Path) -> None:
    scanner = load_scanner()
    artifact = tmp_path / "native.bin"
    artifact.write_text("/Users/runner/work/dependency")
    clean = scanner.scan_path(artifact)
    assert clean.ok
    assert clean.warnings
    artifact.write_text(private_home() + "/work/project")
    leaking = scanner.scan_path(artifact)
    assert not leaking.ok
    assert all("roman" not in value for value in leaking.failures)


def test_actual_packaging_workflow_is_wheel_first_and_non_editable() -> None:
    build = (ROOT / "scripts/build_macos_app.py").read_text()
    spec = (ROOT / "packaging/larp_audio_macos.spec").read_text()
    assert '"bin/uv"), "build", "--wheel"' in build
    assert '"-m", "installer"' in build
    assert '"-e"' not in build and "--editable" not in build
    assert "find_spec" in spec
    assert "src/larp_audio_mvp" not in spec


@pytest.mark.integration
def test_packaged_app_has_no_editable_metadata_or_private_markers() -> None:
    app = ROOT / "dist/LARP Audio.app"
    if not app.is_dir():
        pytest.skip("packaged application is not present")
    scanner = load_scanner()
    result = scanner.scan_path(app)
    assert result.ok, result.failures
    names = [path.name for path in app.rglob("*")]
    assert "direct_url.json" not in names
    assert not any(name.endswith(".egg-link") or name.startswith("__editable__") for name in names)
