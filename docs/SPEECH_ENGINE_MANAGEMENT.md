# Managed speech engine

The installed application owns one recommended multilingual timing engine:
`Systran/faster-whisper-small` at immutable revision
`2ec96c5472da50d38d40c0cfe0602af2e94b4c8a`. The normal UI calls it the
**Recommended speech engine**. Tiny remains a test fixture, not production.

`SpeechEngineDefinition` centralizes the engine ID, revision, expected files,
sizes, SHA-256 values, minimum free storage, language policy and compatible app
version. The engine is stored under platform application data, while results
use Documents, preventing model/output overlap in automatic setup.

The first-launch dialog has one action: **Prepare speech engine**. Downloads use
HTTPS, a pinned revision and bounded chunks. Partial files use an HTTP Range
request; a server that ignores Range causes a safe restart of that file.
Progress, cancellation and retry are explicit. Every completed file is checked
for exact size and SHA-256; a manifest is verified before atomic publication.
Interrupted partial data is never accepted as ready.

Before a Range request, the manager compares the candidate with the immutable
expected size. Oversized and corrupt full-size candidates are removed; valid
full-size candidates are verified without a request; only shorter candidates
may resume. A `206` response must carry a matching `Content-Range`. A server
that returns `200` to Range causes a clean overwrite, never append. HTTP 416,
malformed ranges, and final hash mismatch each permit one clean automatic
restart per file; a repeated defect becomes a controlled error. The previously
published engine is not replaced until every new file and manifest verifies.

Setup lifecycle is explicit: idle/checking/downloading/verifying/installing,
cancelling/cancelled, ready/failed, and closing. Cancelled is not failed.
Dialog close, Escape, main-window close and application quit request cooperative
cancellation and defer object destruction until `QThread.finished` cleanup.
`QThread.terminate()` is never used.

States are `not_installed`, `ready`, and `damaged`. Check, Repair, and Remove are
available in Advanced Settings. Repair redownloads or resumes invalid files.
Audio and scripts are not network inputs; inference uses the verified local
directory with `local_files_only=True`.

The online distribution ships without the 464 MiB engine and needs internet
once. `packaging/offline-engine.json` defines an offline-build input: a
preverified copy of the same pinned engine supplied outside Git. No production
model is included in source or Stage 13 archives.
