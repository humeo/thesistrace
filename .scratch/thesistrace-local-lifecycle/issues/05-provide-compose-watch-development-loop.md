# 05 — Provide the Compose Watch development loop

**What to build:** Provide one foreground development experience in which all
application services remain in Compose while source edits receive immediate,
service-appropriate feedback.

**Blocked by:** 03 — Boot the persistent Development Core through Compose.

**Status:** complete

- [x] `pnpm dev` starts or attaches to the canonical Development topology,
      displays coordinated service logs, and enables Compose Watch.
- [x] A Web source edit is synchronized into the Web container and becomes
      visible through Vite hot module replacement without rebuilding unrelated
      services.
- [x] An API source edit is synchronized and reloads the API without manually
      restarting the complete project.
- [x] A Worker source edit is synchronized and restarts the Worker without
      resetting Development data.
- [x] Changes to Python or JavaScript dependency manifests rebuild only the
      affected service image before it resumes.
- [x] Host dependency directories are neither synchronized into nor overwritten
      by container dependency directories.
- [x] `pnpm dev:logs` follows the canonical Development service logs without
      reconstructing private Compose arguments.
- [x] Interrupting the foreground command stops watching cleanly without
      deleting Development data.
- [x] The watch behavior is verified at observable service and browser seams,
      not by asserting private watch configuration text alone.

## Comments

- Implemented in `89dacf0`; foreground stderr and signal-handling review fixes
  landed in `2e04e50`.
- Live Compose Watch probes verified Web synchronization plus Vite HMR in the
  in-app browser, API synchronization plus Uvicorn reload, Worker restart, and
  a Web-manifest rebuild that recreated only Web. Probe edits were reverted.
- `pnpm dev:logs` followed timestamped canonical logs. API, Worker, and Web had
  no host mounts, and host dependency directories are excluded from build and
  synchronization inputs.
- Real macOS interrupt verification showed ordinary Compose warnings live,
  clean exit status zero, no leaked Watch process, and preserved Development
  services and data. The wrapper narrowly handles Docker Compose v5.0.2's
  known watcher-close panic without suppressing unrelated stderr.
- Two review rounds used the fixed point `d0f7fec`; final Standards and Spec
  reviews reported no findings.
