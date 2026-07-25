# PyInstaller 6.x Windows onedir application. Run only on Windows.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas = [
    (str(root / "resources/bin/windows-x86_64"), "bin/windows-x86_64"),
    (str(root / "resources/bin/manifest.json"), "bin"),
    (str(root / "resources/licenses"), "licenses"),
]
binaries = []
hiddenimports = ["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"]
for package in ("faster_whisper", "ctranslate2", "tokenizers", "av", "spacy", "thinc", "en_core_web_sm"):
    d, b, h = collect_all(package); datas += d; binaries += b; hiddenimports += h
a = Analysis([str(root / "src/larp_audio_mvp/app/desktop.py")], pathex=[str(root / "src")], binaries=binaries, datas=datas, hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "spacy.tests", "thinc.tests", "numpy.tests"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LARP Audio", debug=False, strip=False, upx=False, console=False, icon=str(root / "resources/icons/larp-audio.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LARP Audio")
