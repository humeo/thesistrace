# 01 — Start the empty Web Workspace

**What to build:** A runnable single-node ThesisTrace Workspace whose public
API, persistent worker, Web UI, metadata database, immutable object root, and
acceptance-test harness start together and expose their health.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] One documented local command starts the API, worker, and Web UI.
- [ ] The API reports database, worker, and object-root health through a stable public response.
- [ ] The Web UI renders the empty Workspace and reports unavailable dependencies without inventing resources.
- [ ] Metadata survives a process restart.
- [ ] Backend and frontend focused tests, type checks, and one public-API acceptance test pass.
