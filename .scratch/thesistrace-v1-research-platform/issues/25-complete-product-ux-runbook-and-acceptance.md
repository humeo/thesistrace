# 25 — Complete product UX, runbook, and acceptance

**What to build:** Deliver the coherent single-operator V1 product, documented
operating workflow, and complete evidence that every specified chain works from
the public API and real browser.

**Blocked by:** 05 — Connect the live Tushare source; 17 — Harden ResearchRun lifecycle; 24 — Verify Batch-Incremental Equivalence.

**Status:** resolved

- [x] Resource navigation covers data status, Releases, Field Catalog, Drafts, frozen Definitions, Runs, Attempts, Result Bundles, DailyTracks, Advances, Generations, and Checkpoints.
- [x] Factor and Strategy reports expose all accepted tables, charts, diagnostics, provenance, and downloadable authoritative artifacts without recalculating results in the UI.
- [x] DailyTrack detail shows Head, Generation, lag, blocked frontier, latest factor summaries, account state, and recent events.
- [x] Desktop and narrow-screen browser flows complete fixture Bootstrap, Draft authoring, Run, result inspection, Track activation, later publication, and tracking inspection.
- [x] Error, loading, empty, retry, cancellation, and stopped states are understandable and preserve stable reason codes.
- [x] The operator runbook covers installation, configuration, fixture and live Bootstrap, post-close publication, research, tracking, backup, recovery, and credential boundaries.
- [x] Backend, frontend, calculation, API acceptance, and browser acceptance suites pass from a clean checkout.
- [x] Final code review finds no unresolved correctness, standards, security, or maintainability issue within V1 scope.

## Comments

- Completed the single-operator resource ledger, authoritative Factor and
  Strategy result views, DailyTrack inspection, stable lifecycle diagnostics,
  artifact navigation, Live Tushare publication controls, and responsive
  browser workflow.
- Added the full fixture and live operating runbooks, including source
  credentials, incremental publication, backup, recovery, and explicit live
  acceptance boundaries.
- Final review corrected Dataset publication races, stale Attempt fencing,
  source-value validation, constant Alpha evaluation, Draft freeze ordering,
  correction consistency and dependency replay, adjustment-anchor semantics,
  calculation-kernel dispatch, child-order odd lots, and asynchronous UI
  polling.
- Final `make check` passed: Ruff, 39 backend tests, TypeScript checking,
  production Web build, and independent full narrow-screen and desktop
  real-browser flows. Both browser flows click and inspect every public domain
  resource link.
