# End-user packaging

The production deliverable is a PyInstaller 6 onedir application. It includes
CPython 3.12, PySide6 and Qt plugins (including QtMultimedia), Faster-Whisper,
CTranslate2, tokenizers, PyAV, resources, licenses, FFmpeg and ffprobe. It does
not use the repository `.venv`.

The project package is installed from a normal wheel in a disposable packaging
environment. The release gate rejects local `direct_url.json`, egg links,
editable finders, local-source `.pth` files, personal paths and developer build
prefixes. The same deep policy is applied to the app, app ZIP, mounted DMG and
the nested contents of the release handoff.

Users double-click **LARP Audio.app**. They do not install Python, uv, Homebrew,
FFmpeg, libraries, or a model manually. First run may request one-button speech
engine preparation. Results default to `Documents/LARP Audio Results`; pipeline
publication remains collision-safe and non-overwriting.

The standard UI hides model paths, repository names, media-tool paths, compute
type and beam size. `LARP_AUDIO_DEVELOPER_MODE=1` restores source-development
overrides; production builds do not enable it.

The `1.0.0-rc.9` macOS artifact is arm64 only, ad-hoc signed, and not notarized.
It bundles spaCy and `en_core_web_sm`; syntax analysis needs no runtime download
or user-visible model management.
Gatekeeper may require confirmation for internal distribution. Universal2 and
Intel compatibility are not claimed. Windows must be built/tested on Windows.

Runtime license notices are packaged under `licenses/`. PyInstaller is a
build-only dependency (GPL-2.0-or-later with bootloader exception) and does not
expand the installed user's setup. `certifi` is the only new direct runtime
dependency: it supplies a pinned Mozilla CA bundle so HTTPS engine preparation
works in the frozen Python runtime without weakening certificate verification.

Source releases are created only from the documented allowlist. They contain no
managed engine, model payload, cache, local results, previous archive, app, DMG,
or developer path. The release handoff is separate and contains only the DMG,
the `ditto` app ZIP, checksums, release notes, and installation instructions.
