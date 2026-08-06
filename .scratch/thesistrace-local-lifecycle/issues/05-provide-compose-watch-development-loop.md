# 05 — Provide the Compose Watch development loop

**What to build:** Provide one foreground development experience in which all
application services remain in Compose while source edits receive immediate,
service-appropriate feedback.

**Blocked by:** 03 — Boot the persistent Development Core through Compose.

**Status:** ready-for-agent

- [ ] `pnpm dev` starts or attaches to the canonical Development topology,
      displays coordinated service logs, and enables Compose Watch.
- [ ] A Web source edit is synchronized into the Web container and becomes
      visible through Vite hot module replacement without rebuilding unrelated
      services.
- [ ] An API source edit is synchronized and reloads the API without manually
      restarting the complete project.
- [ ] A Worker source edit is synchronized and restarts the Worker without
      resetting Development data.
- [ ] Changes to Python or JavaScript dependency manifests rebuild only the
      affected service image before it resumes.
- [ ] Host dependency directories are neither synchronized into nor overwritten
      by container dependency directories.
- [ ] `pnpm dev:logs` follows the canonical Development service logs without
      reconstructing private Compose arguments.
- [ ] Interrupting the foreground command stops watching cleanly without
      deleting Development data.
- [ ] The watch behavior is verified at observable service and browser seams,
      not by asserting private watch configuration text alone.
