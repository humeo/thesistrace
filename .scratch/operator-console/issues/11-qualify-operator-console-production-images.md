# 11 — Qualify the Operator Console in final Production Images

**What to build:** Prove that the complete Operator Console, Auth/Core authority
split, durable Worker, and secret boundary work together in the exact final image
topology that will be deployed.

**Blocked by:** 03 — Revoke another Researcher's Login Sessions; 10 — Retain
operation receipts without retaining Data Generations.

**Status:** ready-for-agent

- [ ] Final Auth, Core, Data Operator Worker, Web, Caddy, PostgreSQL, and RustFS
  images start, become healthy, and expose only their intended public and private
  boundaries.
- [ ] The final topology contains exactly one always-running, single-slot Data
  Operator Worker and no obsolete one-shot or parallel Refresh execution path.
- [ ] Production Image Smoke proves Operator assignment and transfer,
  ordinary-Researcher `404`, Operator Proof consumption, Invitation issue and
  reissue, other-Researcher Session revocation, and preserved Operator access.
- [ ] Production Image Smoke proves Market, Financial, and Industry submission,
  global FIFO execution, publication/no-change/degraded outcomes, Dataset Head
  status, Cancel, Retry, Worker restart recovery, and receipt cleanup.
- [ ] The Tushare Secret exists only in the Worker environment, never appears in
  logs or responses, and a missing or placeholder value fails Worker startup
  without breaking durable submission through healthy Core.
- [ ] Real browser E2E through Caddy uses one Operator and one ordinary
  Researcher, real PostgreSQL and RustFS, a Resend fake, and versioned Tushare
  replay to cover every critical user workflow.
- [ ] Browser acceptance covers desktop, collapsed sidebar, tablet, mobile
  navigation drawer, keyboard-only operation, focus containment and restoration,
  Escape behavior, reduced motion, accessible names, touch targets, and
  non-color-only state.
- [ ] The Console follows the repository's dense, dark product workbench without
  adding a generic administration dashboard, light-theme fallback, or hidden
  critical provenance.
- [ ] Ordinary qualification uses no public internet and no live Tushare request;
  live Tushare verification remains a separate explicit gate.
- [ ] The deployment and operational documentation describes the new Worker,
  assignment/transfer commands, secret boundary, submission-versus-publication
  distinction, recovery behavior, and supported Console operations.
- [ ] The complete local release command passes against committed final changes,
  and diagnostic artifacts identify image versions, operation IDs, request IDs,
  logs, responses, and browser screenshots on failure.
