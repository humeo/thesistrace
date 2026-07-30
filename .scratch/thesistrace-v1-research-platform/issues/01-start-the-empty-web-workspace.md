# 01 — Start the empty Web Workspace

**What to build:** A runnable single-node ThesisTrace Workspace whose public
API, persistent worker, Web UI, metadata database, immutable object root, and
acceptance-test harness start together and expose their health.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] One documented local command starts the API, worker, and Web UI.
- [x] The API reports database, worker, and object-root health through a stable public response.
- [x] The Web UI renders the empty Workspace and reports unavailable dependencies without inventing resources.
- [x] Metadata survives a process restart.
- [x] Backend and frontend focused tests, type checks, and one public-API acceptance test pass.

## Comments

- Implemented the single-node API, SQLite metadata store, object-root probe,
  persistent worker heartbeat, and research-ledger Web Workspace.
- Verified with backend acceptance, lint, frontend type/build, and Playwright
  browser acceptance checks.
