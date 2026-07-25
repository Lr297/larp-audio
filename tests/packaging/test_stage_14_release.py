from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QPushButton

from larp_audio_mvp.gui.main_window import MainWindow
from larp_audio_mvp.runtime import ApplicationPaths
from larp_audio_mvp.speech_engine import SpeechEngineManager

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.1.0"
ICON_NAMES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def test_master_icon_is_high_resolution_alpha_and_physically_rounded() -> None:
    path = ROOT / "resources/icons/larp_audio_master.png"
    image = QImage(str(path))
    assert not image.isNull()
    assert (image.width(), image.height()) == (1024, 1024)
    assert image.hasAlphaChannel()
    for x, y in ((0, 0), (1023, 0), (0, 1023), (1023, 1023), (30, 30)):
        assert image.pixelColor(x, y).alpha() == 0
    assert image.pixelColor(512, 512).alpha() == 255
    assert image.pixelColor(56, 512).alpha() > 0
    assert image.pixelColor(512, 56).alpha() > 0


def test_complete_iconset_is_derived_at_expected_sizes() -> None:
    iconset = ROOT / "resources/icons/larp_audio.iconset"
    assert {path.name for path in iconset.glob("*.png")} == set(ICON_NAMES)
    for name, size in ICON_NAMES.items():
        image = QImage(str(iconset / name))
        assert not image.isNull()
        assert (image.width(), image.height()) == (size, size)
        assert image.hasAlphaChannel()
        assert image.pixelColor(0, 0).alpha() == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="iconutil is a macOS tool")
def test_icns_is_valid_and_round_trips(tmp_path: Path) -> None:
    source = ROOT / "resources/icons/larp_audio.icns"
    assert source.is_file() and source.stat().st_size > 0
    destination = tmp_path / "roundtrip.iconset"
    subprocess.run(["iconutil", "-c", "iconset", str(source), "-o", str(destination)], check=True)
    assert {path.name for path in destination.glob("*.png")} == set(ICON_NAMES)


def test_release_version_and_icon_are_consistent_in_sources() -> None:
    assert 'version = "1.0.0rc9"' in (ROOT / "pyproject.toml").read_text()
    version_source = (ROOT / "src/larp_audio_mvp/version.py").read_text()
    assert f'RELEASE_VERSION = "{VERSION}"' in version_source
    spec = (ROOT / "packaging/larp_audio_macos.spec").read_text()
    assert "resources/icons/larp_audio.icns" in spec
    assert '"CFBundleIconFile": "larp_audio.icns"' in spec
    assert f'"CFBundleShortVersionString": "{VERSION}"' in spec
    assert '"CFBundleVersion": "10009"' in spec
    assert "LARP-Audio.icns" not in spec


def test_application_sets_icon_before_main_window_and_user_about_copy_is_clean() -> None:
    application = (ROOT / "src/larp_audio_mvp/gui/application.py").read_text()
    assert "application.setWindowIcon" in application
    create_body = application[application.index("def create_application"):application.index("def run")]
    assert create_body.index("application.setWindowIcon") < create_body.index("apply_theme")
    main = (ROOT / "src/larp_audio_mvp/gui/main_window.py").read_text()
    about = main[main.index("def show_about"):main.index("def dragEnterEvent")]
    for forbidden in ("Faster-Whisper", "CTranslate2", "model.bin", "Hugging Face", "FFmpeg path", "ffprobe path"):
        assert forbidden not in about


def test_visible_consumer_copy_does_not_expose_developer_technology(qapp, tmp_path: Path) -> None:
    paths = ApplicationPaths(tmp_path / "data", tmp_path / "Documents/LARP Audio Results", tmp_path / "logs")
    window = MainWindow(
        settings=QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat),
        application_paths=paths,
        speech_engine_manager=SpeechEngineManager(paths.data_directory),
        developer_mode=False,
    )
    window.show()
    qapp.processEvents()
    visible_copy = " ".join(
        widget.text()
        for widget in [*window.findChildren(QLabel), *window.findChildren(QPushButton)]
        if widget.isVisible()
    )
    for forbidden in ("Faster-Whisper", "CTranslate2", "model.bin", "Hugging Face", "TOML", "FFmpeg path", "ffprobe path"):
        assert forbidden not in visible_copy
    assert "PREPARE ENGINE" in visible_copy
    window.close()


@pytest.mark.integration
def test_packaged_app_contains_rc_icon_and_plist_metadata() -> None:
    app = ROOT / "dist/LARP Audio.app"
    if not app.is_dir():
        pytest.skip("packaged application is not present")
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert plist["CFBundleShortVersionString"] == VERSION
    assert plist["CFBundleVersion"] == "10009"
    icon_name = plist["CFBundleIconFile"]
    assert icon_name == "larp_audio.icns"
    assert (app / "Contents/Resources" / icon_name).is_file()
    master = app / "Contents/Resources/icons/larp_audio_master.png"
    assert master.is_file()
    assert QImage(str(master)).pixelColor(0, 0).alpha() == 0
