# Subtitle output safety

## Stage 11.1 package boundary

All published JSON is recursively scanned for POSIX, Windows-drive, UNC,
`file://`, input/model/workspace/temp, and developer-root paths. Exact script
and ASR observation text fields are not interpreted as metadata because user
content may legitimately contain a path; those strings remain unchanged.
Metadata fields containing `path` or `directory` accept only safe basenames.
The ZIP validator repeats generic privacy checks on every embedded JSON using
bounded streaming reads.

`subtitle_blocks.json` must bind the actual alignment SHA-256, script hash and
exact text, sample rate, and both timeline totals. SRT is validated from that
strict document and uses the cleaned timeline. Passing an individual JSON
schema is insufficient when its provenance conflicts with another artifact.

## Preflight path plan

`SubtitlePathPlan` is immutable and is built before `mkdir`, chunking, staging,
or publication. It contains the resolved alignment input, JSON/SRT finals,
`.partial` staging paths, `.rollback` paths, and normalized identities. Every
pair must be unique. Identity uses absolute normalized paths,
`Path.resolve(strict=False)`, `os.path.normcase`/`normpath`, and `samefile` for
existing filesystem objects. This catches `.`/`..`, parent-directory symlinks,
case aliases on case-insensitive systems, and detectable hard links.

Input symlinks are allowed after resolution. A final output path that is itself
a symlink is rejected, so publication never follows an output link. Existing
outputs must be regular files. Alignment must exist and resolve to a regular
file. Directories, devices, FIFOs, sockets, occupied staging/rollback paths, and
parents whose nearest existing ancestor is not a directory are rejected.

The standard library cannot reliably detect every future race or a
case-insensitive alias for two paths that do not yet exist on every platform.
Preflight minimizes these risks; individual publication still relies on the
same-filesystem atomicity of `os.replace`.

## Controlled errors

- `SUBTITLE_OUTPUT_COLLISION`: any planned identity collision.
- `SUBTITLE_OUTPUT_PATH_INVALID` / `SUBTITLE_OUTPUT_PARENT_INVALID`: invalid
  source, final, staging, type, or parent.
- `SUBTITLE_OUTPUT_PREPARATION_FAILED`: directory/staging/cleanup failure.
- `SUBTITLE_EXISTING_OUTPUT_READ_FAILED`: an existing output cannot be safely
  backed up, is invalid UTF-8, disappears, or exceeds 64 MiB.
- `SUBTITLE_PUBLICATION_FAILED`: replace or final verification failure.
- `SUBTITLE_ROLLBACK_FAILED`: best-effort restoration was incomplete.

CLI errors contain the stable code on stderr, return status 2, omit the success
JSON and do not show a traceback by default.

## Pair publication guarantee

Both new payloads are rendered and strictly validated in staging before either
final path changes. JSON is replaced first and SRT second. If either publication
or final verification fails after a replacement, every replaced output is
restored from its prior bytes or removed if it did not previously exist.
Successful rollback leaves the original pair and removes staging. This is a
best-effort two-file transaction, not true cross-file atomicity. If restoration
fails, the distinct rollback error reports the failure and a completed rollback
staging file is deliberately retained for recovery.
