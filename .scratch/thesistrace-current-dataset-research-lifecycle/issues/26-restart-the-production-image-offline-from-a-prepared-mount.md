# 26 — Restart the Production Image offline from a prepared mount

**What to build:** Qualify the final Production Image to start, execute dated
research, and restart from a prepared persistent Canonical Data mount without
downloading or mutating market data.

**Blocked by:** 14 — Execute each Attempt against its start-time Head; 22 — Contract fixed Research Period compatibility; 24 — Contract the permanent Dataset Release path.

**Status:** complete

- [x] Final backend and Web images start with real runtime dependencies and one mounted, prepared, compatible Canonical Data Store.
- [x] Fresh database migration, liveness, system health, and readiness pass, and public Coverage and data-through match the prepared Head.
- [x] Network isolation or a fail-on-call source proves that API and Worker startup, a short ResearchRun, and service restart invoke no Tushare, Bootstrap, or Refresh path.
- [x] A short dated ResearchRun completes through the Worker and publishes one legal variable-length four-value Result Bundle.
- [x] Restarting API and Worker preserves the authoritative Head, Run status, Result, and readiness without another execution or data download.
- [x] Verification targets the built Production Image rather than source processes and records image identity, container exit status, health state, and service logs on failure.
- [x] This smoke remains narrowly scoped and does not absorb the browser journey, live Tushare contract, or the complete recovery and concurrency matrices.

## Comments

- Implemented by `86f1a3c test(deploy): qualify offline production images`;
  evidence and restart hardening are in `090e4c2` and `ee662a1`.
- Final Production Image Smoke run
  `20260810t110619z-48411-994a74f0` completed with status 0 on an internal-only
  Compose network. It built the backend and Web images, migrated a fresh real
  PostgreSQL database, mounted prepared Canonical data, executed one three-session
  ResearchRun through the real Worker, and reopened the same four-value Result
  after API and Worker restart.
- The smoke snapshots the complete Run and Attempt rows, Result manifest,
  public result, readiness, and mounted-data digest before restart and requires
  exact equality afterward. The final full integration gate also passed
  `124 passed` plus the dedicated PostgreSQL restart test (`1 passed`).
  Standards and Spec reviews ended with zero material findings.
