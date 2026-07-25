# PyInstaller 6.x macOS onedir application. Run from the repository root.
from pathlib import Path
from importlib.util import find_spec
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
entry_spec = find_spec("larp_audio_mvp.app.desktop")
if entry_spec is None or entry_spec.origin is None:
    raise RuntimeError("larp_audio_mvp wheel is not installed in the packaging environment")
entrypoint = Path(entry_spec.origin)
datas = [
    (str(root / "resources/bin/macos-arm64"), "bin/macos-arm64"),
    (str(root / "resources/bin/manifest.json"), "bin"),
    (str(root / "resources/licenses"), "licenses"),
    (str(root / "resources/icons/larp_audio_master.png"), "icons"),
]
binaries = []
hiddenimports = ["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"]
for package in ("faster_whisper", "ctranslate2", "tokenizers", "av", "spacy", "thinc", "en_core_web_sm"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

datas = [d for d in datas if not d[0].endswith("direct_url.json")]

a = Analysis(
    [str(entrypoint)],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "spacy.tests", "thinc.tests", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LARP Audio", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LARP Audio")
app = BUNDLE(
    coll,
    name="LARP Audio.app",
    icon=str(root / "resources/icons/larp_audio.icns"),
    bundle_identifier="audio.larp.desktop",
    info_plist={
        "CFBundleDisplayName": "LARP Audio",
        "CFBundleIconFile": "larp_audio.icns",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "100",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSMicrophoneUsageDescription": "LARP Audio does not record audio; it processes files you select.",
    },
)
