# Packaged artifact privacy

## Threat model and release blockers

A distributable can reveal a developer identity even when source archives are
clean. Compiler configuration strings, native debug data, Python installation
metadata, nested archives and mounted disk images are all in scope. A release is
blocked when any public artifact contains the active home directory, repository
or workspace, the project-specific vendor build directory, a local `file://`
source URL, or editable-install metadata.

The Stage 13.1 artifacts demonstrated both principal failure modes. FFmpeg's
compiled configuration retained a developer-specific `--prefix`, while a
project `direct_url.json` retained the local editable checkout URL. Post-build
deletion is not the remedy: both build roots now avoid producing the data.

## Privacy-safe FFmpeg build

`scripts/build_ffmpeg_macos.py` verifies the pinned official FFmpeg 8.1.2 source
archive, extracts it into an ephemeral directory and uses the stable virtual
prefix `/opt/larp-audio/ffmpeg`. Compilation is source-relative. Compiler prefix
mapping is not currently added because the release build emits no temporary or
checkout path; adding unneeded flags would change the verified configuration.
The checked-in executable strings are nevertheless scanned after every build.

## Wheel-first application packaging

`scripts/build_macos_app.py` creates a disposable Python 3.12 virtual
environment, installs the exact versions in
`packaging/requirements-macos-arm64.txt`, builds a normal wheel, and installs it
with the wheel installer before invoking PyInstaller. The spec resolves the
installed entry point. It does not add `src` to `pathex` and the process never
uses `pip -e` or the repository `.venv`.

The clean environment and final app are rejected if they contain project
`direct_url.json`, `*.egg-link`, `__editable__*`, a local-source `.pth`, a local
source URL, or a private build/source path.

## Unified deep scanner

`scripts/scan_release_privacy.py TARGET...` supports ordinary files and
directories, `.app` bundles, ZIP and ZIP-in-ZIP, and DMG on macOS. It checks raw
bytes for exact private markers and uses `strings -a` for Mach-O diagnostics.
ZIP processing reads the central directory and applies limits for recursion,
entry count, expanded bytes and compression ratio; a large outer ZIP is never
accepted merely because it exceeds a size threshold. DMGs are verified,
mounted read-only, recursively scanned and detached in `finally` cleanup.

Generic third-party paths such as `/Users/runner/...` are warnings. They become
failures only when they contain an active private marker or project-specific
developer path. Diagnostics name the artifact and failure category, never the
matched secret value. The release gate covers source archives, bundled media,
the app, app ZIP, mounted DMG and the recursively inspected release handoff.

## Release procedure

1. Rebuild and validate the pinned media tools.
2. Build the app from a wheel in the clean environment.
3. Run the scanner on the app before signing, then verify the signature.
4. Create the app ZIP with `ditto`, create/verify the DMG, and scan both.
5. Create allowlisted source archives and scan them.
6. Create the minimal release handoff and scan its nested ZIP and DMG.
7. Write final external checksums and do not modify sealed artifacts afterward.

The handoff's embedded checksum file covers its payload but cannot contain the
hash of the ZIP that contains it. The final external `dist/SHA256SUMS.txt`
additionally records the handoff hash; this avoids a mathematically impossible
self-referential archive hash.
