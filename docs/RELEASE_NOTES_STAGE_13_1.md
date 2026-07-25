# LARP Audio Stage 13.1 release notes

This maintenance release preserves the approved one-page interface and output
schemas while hardening distribution and first-run setup.

- Source archives now use a positive allowlist and exclude speech models,
  inference caches, application data, previous archives, and generated results.
- Public-source preflight checks privacy markers, secret-like values, nested
  archives, unapproved media, and unexpected large files.
- Interrupted model downloads safely recover from invalid full-size partials,
  HTTP 416, ignored Range requests, malformed `Content-Range`, and final hash
  mismatch with one bounded clean restart per file.
- Cancelling setup is distinct from failure. Dialog/app close waits for the
  setup worker and does not destroy a running QThread.
- The macOS arm64 app and DMG were rebuilt; the DMG includes an Applications
  shortcut. The build is ad-hoc signed and is not notarized.

No cloud backend, telemetry, updater, new runtime dependency, model payload,
subtitle schema change, or Stage 14 feature was added.
