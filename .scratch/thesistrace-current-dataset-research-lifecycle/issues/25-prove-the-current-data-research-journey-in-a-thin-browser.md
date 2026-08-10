# 25 — Prove the current-data research journey in a thin browser

**What to build:** Prove the visible current-data research loop in one thin
real-browser journey without repeating the backend retry, concurrency,
Refresh, garbage-collection, or Reset matrices.

**Blocked by:** 09 — Serve the mounted Head as read-only Data Overview; 13 — Admit dated ResearchRuns against current Data; 14 — Execute each Attempt against its start-time Head; 17 — Start and catch up a DailyTrack from terminal state.

**Status:** complete

- [ ] The browser runs against real API, Worker, PostgreSQL, RustFS, and a prepared temporary Mounted Canonical Data Store rather than mocked HTTP responses.
- [ ] Data page shows only read-only Data Overview and manual read refresh, with no Update control, mutation polling, Release or Generation identifier, history, or operator state.
- [ ] Definition authoring visibly requires both dates for Run and demonstrates at least one actionable date error without creating a ResearchRun.
- [ ] A short dated ResearchRun progresses through the real Worker to success and renders Factor Summary, Strategy Summary, variable Daily Observations, and Terminal Strategy State.
- [ ] The successful Result explicitly starts a DailyTrack whose visible state continues from the historical terminal account and progresses toward current Head.
- [ ] No page exposes Data Operator Attempts, pin or fence internals, object or manifest locations, Generation browsing, or DailyTrack Checkpoint manifests; legitimate ResearchRun lifecycle status and permitted provenance remain visible under their product contract.
- [ ] State waits use timeout-bounded condition polling rather than fixed sleeps, and failure evidence includes a screenshot, request responses, and relevant service logs.
- [ ] Default execution is network-independent and uses no paid credentials; the journey does not duplicate full backend failure matrices.
