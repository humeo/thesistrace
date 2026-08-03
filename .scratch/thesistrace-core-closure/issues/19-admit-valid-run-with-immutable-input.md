# 19 — Admit a valid Run with immutable input

**What to build:** Save valid current Definition content and atomically create
one queued ResearchRun containing the complete private immutable execution
input.

**Blocked by:** 07, 18.

**Status:** ready-for-agent

- [ ] Run locks the Definition, checks expected revision, saves the submitted
  content, and advances revision once.
- [ ] Admission resolves the latest successful Dataset Release at that moment
  and injects field bindings plus fixed Strategy, cash, execution, cost,
  risk-free, numeric, and semantic contracts.
- [ ] Definitions calls private ResearchRun admission inside the same concrete
  PostgreSQL transaction while both modules retain their own SQL.
- [ ] Definition, accepted receipt, immutable input, and queued ResearchRun
  commit once or not at all.
- [ ] Matching accepted replay returns the original revision and Run ID without
  another write; conflicting fingerprint reuse returns a conflict.
- [ ] Immutable input has no separate Snapshot ID, table projection, URL, list,
  or Web page.
- [ ] ResearchRun can be created only by Definition Run or ResearchRun Rerun;
  no generic create, update, or delete operation exists.
- [ ] Editing and running again creates a distinct ResearchRun from the new
  content; it is not Rerun.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with success,
  rollback, replay, conflict, latest-Release, and edited-second-Run cases.
- Run `bun run --cwd web test:e2e` and confirm one Run action navigates to a new
  queued ResearchRun without exposing a Snapshot resource.

## Comments
