# 07 — Expose unified Dataset Operational Status

**What to build:** Give the Operator one safe, dense Data surface that identifies
the Dataset Head currently used by research and makes the ordered lifecycle of
Market, Financial, and Industry Refreshes understandable without reading logs or
storage internals.

**Blocked by:** 05 — Run Financial Refresh through the durable Data Operator
Worker; 06 — Run Industry Refresh through the durable Data Operator Worker.

**Status:** ready-for-agent

- [ ] `/operator/data` leads with current Dataset Head identity and readiness and
  shows the most recent Data Refresh Operation for each Refresh kind.
- [ ] All three kinds share one global FIFO with at most one running operation;
  cross-kind integration tests prove acceptance order and absence of concurrent
  Dataset Head writers.
- [ ] Operation history is reverse chronological, stable, and server-paginated in
  pages of 50.
- [ ] Visible operation state distinguishes accepted, running phase, attempt,
  last heartbeat, published, no change, degraded, failed, and cancelled using
  text rather than color alone.
- [ ] A detail drawer shows safe target, idempotency key, timestamps, counts,
  outcome, and stable failure code while excluding raw upstream responses,
  secrets, manifests, object paths, and unrestricted Dataset history.
- [ ] A visible page containing non-terminal work polls every five seconds,
  stops after terminal state, and refreshes immediately on focus or network
  recovery; a manual Reload action is always available.
- [ ] No SSE, WebSocket, event bus, service worker, or hidden background polling
  is introduced.
- [ ] The ordinary Researcher-facing Data Overview remains read-only and does not
  expose Operator controls or operation history.
- [ ] API and UI tests cover safe projection, stable pagination, each lifecycle
  state, polling start/stop, focus/network recovery, manual reload, and ordinary
  Researcher `404` behavior.
- [ ] A real browser test verifies the dense responsive table, detail drawer,
  keyboard navigation, accessible status meaning, and all three Refresh kinds.
