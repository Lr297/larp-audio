# Release hygiene and public-source policy

Stage 13.1 uses a positive source allowlist: `src`, `tests`, `docs`, `scripts`,
`packaging`, `resources`, `.github`, and the named project metadata files.
Historical generated demos, reference material, local model directories,
application data, work/build/dist/output trees, and previous stage reports are
not public snapshot inputs. Archive creation fails if any selected entry is a
model payload, cache, runtime lock, partial, nested archive, application bundle,
DMG, unapproved media file, private path, or secret-like value.

The checked-in macOS arm64 FFmpeg and ffprobe files are the only documented
large vendor binaries. Their origin, LGPL license, hashes, and build flags live
in `docs/BUNDLED_FFMPEG.md` and `resources/bin/manifest.json`. Files over 10 MiB
warn; unexpected files over 50 MiB fail. The synthetic Stage 13 tone is the only
allowlisted raw-audio fixture.

`scripts/check_public_repository.py` evaluates the intended public snapshot,
not ignored local developer data. It also invokes the unified deep scanner from
`scripts/scan_release_privacy.py`; that scanner covers raw binary markers,
Mach-O strings, package metadata, mounted DMGs and bounded nested ZIPs. It scans names and text, nested ZIP entries,
common private-key/token forms, platform home markers, unexpected media, and
size policy. `scripts/create_stage_13_1_archives.py` runs the same checks both
before writing and after reopening each ZIP with CRC verification. CI runs the
preflight, compileall, and release-safety tests without publishing a release,
model, or Pages site.

The application model manifest, pinned revision, filenames, sizes and SHA-256
remain source data; actual model bytes and inference caches remain local and are
ignored. A clean source snapshot can therefore be reviewed and built without
carrying user or model data.
