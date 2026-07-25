# Windows build

Windows must be built on Windows x86-64. Supply pinned distributable FFmpeg and
ffprobe files, record source/license/hashes in the media manifest, then run:

```powershell
uv sync --frozen
scripts/build_windows.ps1
```

The spec includes Python, Qt and native STT libraries. The build fails when
media resources are absent. `.github/workflows/build-windows.yml` uses a real
Windows Server 2022 runner and uploads a private CI artifact; it creates no
public release or Pages site. A Windows clean-machine run must verify launch,
engine setup, processing, restart/reuse and offline reuse. This macOS stage does
not claim those checks passed.
