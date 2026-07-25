# Bundled FFmpeg and ffprobe

Installed LARP Audio resolves media tools from application resources. It does
not use Homebrew or `PATH`. Explicit paths and `PATH` fallback exist only with
`LARP_AUDIO_DEVELOPER_MODE=1` in a source checkout.

The macOS arm64 binaries were built from official FFmpeg 8.1.2 source
(`https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz`, SHA-256
`464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c`).
They are static, network-disabled builds configured without GPL or nonfree
components. The binaries are LGPL-2.1-or-later. Exact flags and hashes are in
`resources/bin/manifest.json`; license text is in `resources/licenses/ffmpeg/`.

The release build uses the documented privacy-neutral virtual prefix
`/opt/larp-audio/ffmpeg`. `scripts/build_ffmpeg_macos.py` verifies the source
hash, builds from a temporary clean extraction and atomically publishes both
tools. Temporary compiler paths were not observed in distributed strings, so
compiler prefix-map flags are not currently necessary. `strings`, raw-marker,
Mach-O architecture, dependency, empty-PATH execution and manifest-hash checks
are mandatory before packaging.

Resolution order is bundled resource, explicit developer override, then system
PATH only in source developer mode. Missing installed resources produce a
controlled reinstall/repair message. `scripts/verify_packaged_app.py` executes
both tools with an empty PATH.

Windows binaries are not cross-built on macOS. The Windows job fails unless
pinned, verified `ffmpeg.exe` and `ffprobe.exe` are provisioned first.
