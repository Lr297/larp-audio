# Windows media resources

The Windows build job must place pinned `ffmpeg.exe` and `ffprobe.exe` here and
verify their SHA-256 values before packaging. They are deliberately not copied
from the macOS host or silently downloaded by PyInstaller.
