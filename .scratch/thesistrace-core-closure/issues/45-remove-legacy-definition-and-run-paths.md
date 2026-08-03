# 45 — Remove legacy Definition and ResearchRun paths

**What to build:** Delete old Definition, Save/Run, ResearchRun lifecycle, and
Result paths after the canonical modules own every active research action.

**Blocked by:** 44.

**Status:** ready-for-agent

- [ ] Draft, separately browsable frozen version, old Save-then-Run sequencing,
  and legacy Definition routes are removed.
- [ ] Old ResearchRun creation, execution, Result, Cancel, Rerun, and internal
  lifecycle projections are removed with their callers.
- [ ] Legacy Definition and ResearchRun tests are removed or migrated to the
  mutable Definition, atomic Run, immutable-input, and bounded Result contracts.
- [ ] No path can create a ResearchRun outside Definition Run or ResearchRun
  Rerun, and no generic create, update, or delete route remains.
- [ ] Canonical Definition revision handling, Run receipts, PostgreSQL worker,
  standard S3 Publication, Cancel fencing, and exact-input Rerun remain
  unchanged.
- [ ] Quantitative code now owned by the Research Kernel is preserved rather
  than deleted with an old lifecycle caller.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/architecture tests/integration tests/acceptance`
  with all legacy Definition and ResearchRun entrypoints absent.
- Run `bun run --cwd web test:e2e` and confirm Save, rejected Run, successful
  Result, edited Run, Cancel, and Rerun use only canonical routes.

## Comments
