$ErrorActionPreference = "Stop"
if (-not (Test-Path "resources/bin/windows-x86_64/ffmpeg.exe") -or -not (Test-Path "resources/bin/windows-x86_64/ffprobe.exe")) { throw "Pinned Windows ffmpeg and ffprobe resources are required." }
python -m PyInstaller --noconfirm --clean packaging/larp_audio_windows.spec
