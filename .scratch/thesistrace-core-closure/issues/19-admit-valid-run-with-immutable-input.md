# 19 — Admit a valid Run with immutable input

**What to build:** Save valid current Definition content and atomically create
one queued ResearchRun containing the complete private immutable execution
input.

**Blocked by:** 07, 18.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Run locks the Definition, checks expected revision, saves the submitted
  content, and advances revision once.
- [x] Admission resolves the latest successful Dataset Release at that moment
  and injects field bindings plus fixed Strategy, cash, execution, cost,
  risk-free, numeric, and semantic contracts.
- [x] Definitions calls private ResearchRun admission inside the same concrete
  PostgreSQL transaction while both modules retain their own SQL.
- [x] Definition, accepted receipt, immutable input, and queued ResearchRun
  commit once or not at all.
- [x] Matching accepted replay returns the original revision and Run ID without
  another write; conflicting fingerprint reuse returns a conflict.
- [x] Immutable input has no separate Snapshot ID, table projection, URL, list,
  or Web page.
- [x] ResearchRun can be created only by Definition Run or ResearchRun Rerun;
  no generic create, update, or delete operation exists.
- [x] Editing and running again creates a distinct ResearchRun from the new
  content; it is not Rerun.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_research_run_admission.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must cover accepted admission, forced rollback, replay,
fingerprint conflict, latest-Release resolution, and a distinct edited second
Run while inspecting the complete private immutable input. The browser must use
one Run request, navigate to the new queued ResearchRun, and expose no Snapshot
resource, identifier, URL, or list.

## Comments

- Added the canonical `research_run` module and its owned PostgreSQL schema.
  Definitions invokes its private `admit` seam with the same concrete
  transaction; neither module reaches into the other's schema. Admission has no
  public generic create/update/delete API.
- A successful Run saves the submitted Definition content and one accepted
  receipt, resolves the latest successful Release through Data's private
  projection, and inserts one queued ResearchRun with its complete private
  immutable input. Any failure rolls back all four writes.
- The immutable input freezes Release field bindings plus the fixed v1
  Strategy, CNY 10,000,000 initial cash, next-open full-fill execution, cost,
  zero risk-free, numeric, and semantic contracts. It has no Snapshot resource,
  ID, endpoint, route, or page.
- Accepted idempotent replay returns the original Definition revision and Run
  ID without writing again; conflicting request fingerprint reuse returns 409.
  Editing and running again creates a distinct Run from the newly saved
  content.
- The final ticket backend command passed `82 passed, 1 warning` in `376.39s`.
  It proves two published Releases select the latest, the complete immutable
  input is frozen, an actual admitted insert rolls back with its transaction,
  replay/conflict are stable, and missing current Release field bindings reject
  without creating a Run.
- The final Core browser command passed `7 passed` in `47.3s`. The accepted Run
  makes one request, navigates to the queued ResearchRun, and exposes no
  Snapshot surface.
- Independent review initially found missing current-Release field validation,
  a rollback test that threw before the real admission insert, and insufficient
  proof of latest-Release selection. All three were fixed and re-reviewed;
  final review passed `Standards: PASS` and `Spec: PASS` with no findings.
- The legacy workspace E2E had two unrelated timing races exposed by the full
  gate: asynchronous fixture/contract publication used a 5-second default, and
  the test required the transient `queued` state even when the worker had
  already advanced to `running`. The test now waits on durable boundaries while
  retaining the required `succeeded` terminal assertion; narrow and desktop
  runs passed independently before the repository gate.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `519 passed, 57 skipped, 2 warnings` in `1093.37s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `57.5s` and
  about `1.1m`.
