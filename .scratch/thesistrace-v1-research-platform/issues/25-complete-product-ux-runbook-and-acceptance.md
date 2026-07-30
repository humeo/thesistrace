# 25 — Complete product UX, runbook, and acceptance

**What to build:** Deliver the coherent single-operator V1 product, documented
operating workflow, and complete evidence that every specified chain works from
the public API and real browser.

**Blocked by:** 05 — Connect the live Tushare source; 17 — Harden ResearchRun lifecycle; 24 — Verify Batch-Incremental Equivalence.

**Status:** ready-for-agent

- [ ] Resource navigation covers data status, Releases, Field Catalog, Drafts, frozen Definitions, Runs, Attempts, Result Bundles, DailyTracks, Advances, Generations, and Checkpoints.
- [ ] Factor and Strategy reports expose all accepted tables, charts, diagnostics, provenance, and downloadable authoritative artifacts without recalculating results in the UI.
- [ ] DailyTrack detail shows Head, Generation, lag, blocked frontier, latest factor summaries, account state, and recent events.
- [ ] Desktop and narrow-screen browser flows complete fixture Bootstrap, Draft authoring, Run, result inspection, Track activation, later publication, and tracking inspection.
- [ ] Error, loading, empty, retry, cancellation, and stopped states are understandable and preserve stable reason codes.
- [ ] The operator runbook covers installation, configuration, fixture and live Bootstrap, post-close publication, research, tracking, backup, recovery, and credential boundaries.
- [ ] Backend, frontend, calculation, API acceptance, and browser acceptance suites pass from a clean checkout.
- [ ] Final code review finds no unresolved correctness, standards, security, or maintainability issue within V1 scope.
