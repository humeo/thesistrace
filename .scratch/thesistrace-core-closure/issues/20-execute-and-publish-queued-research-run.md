# 20 — Execute and publish one queued ResearchRun

**What to build:** Move one queued ResearchRun through its PostgreSQL-owned
worker and pure Kernel to one durable, completely published success.

**Blocked by:** 19.

**Status:** complete

**Implementation:** complete

- [x] A ResearchRuns-owned processor claims queued work and projects it as
  `running`; no global job table, dispatch command, or outbox is involved.
- [x] The worker loads only the pinned Release through Data's canonical loader
  and executes the stored immutable input through Kernel Run.
- [x] It prepares the Result through shared Publication and commits the verified
  reference with `succeeded` under the current fence.
- [x] Result provenance binds the ResearchRun immutable input, pinned Dataset
  Release, calculation contracts, and Kernel semantic versions through the
  shared Publication contract.
- [x] Publication failure or a stale fence exposes no partial Result and cannot
  record success.
- [x] Attempt, claim, lease, heartbeat, and object details remain private.
- [x] ResearchRun list and detail retain the queued, running, and succeeded
  product projections across HTTP and worker restart.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_research_run_execution.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must use real PostgreSQL and RustFS to observe one admitted
Run as queued, claimed running, and durably succeeded; verify its published
Result provenance; restart the HTTP/runtime objects and reopen the same Run
without another execution; and prove publication failure plus a stale fence
cannot expose a partial Result or record success. The browser must refresh the
same Run from queued through running to succeeded while showing only product
projections and no Attempt, claim, lease, heartbeat, fence, manifest, or object
details.

## Comments

- Added a ResearchRuns-owned PostgreSQL processor that claims one queued Run
  with `FOR UPDATE SKIP LOCKED`, records a private fenced Attempt, and projects
  the Run as `running`. The Core worker calls this module seam directly; no
  global job table, dispatch command, or outbox was introduced.
- Execution loads the pinned Release only through Data's canonical loader,
  trims the source to the required 756 sessions, and passes the stored immutable
  input to the pure Kernel. The Result provenance binds the immutable-input
  digest, Dataset Release, calculation contracts, and semantic versions.
- Publication prepares canonical bytes through the shared Publication module.
  Its verified manifest reference, Attempt success, and Run `succeeded` state
  commit in one PostgreSQL transaction only while the fence remains current.
  Injected publication failure rolls back every publication row; a stale fence
  cannot publish or record success.
- The bounded Result contains Factor Summary, Strategy Summary, exactly 504
  canonical Strategy Daily Observations, and Terminal Strategy State. Daily
  observations retain the 11 established evidence fields, including per-session
  transaction cost and three per-session rejection counts, while derivable
  returns, cash ratio, and cumulative cost are omitted. The exact published
  bundle remains at or below 1 MiB.
- HTTP and Web expose only ResearchRun product fields and poll queued/running to
  terminal status. Attempt, claim, lease, heartbeat, fence, manifest, and object
  mechanics remain private; a restarted runtime reopens the same succeeded Run
  without executing it again.
- The final ticket backend command passed `83 passed, 1 warning` in `200.22s` on
  real PostgreSQL and RustFS. One earlier invocation was invalidated when the
  shared containers were stopped by a concurrent independent-review cleanup;
  its connection-refused failures were excluded and the same command was rerun
  cleanly after the reviewer finished.
- The final Core browser command passed `7 passed` in `32.2s`, including the
  visible queued to running to succeeded transition and the private-mechanics
  boundary.
- Independent review first found that the new JSON Result daily projection did
  not match the established canonical daily field contract. Commit `5808ba5`
  restored the exact 11-field projection, per-session cost, and rejection
  counts. Final review passed `Standards: PASS` and `Spec: PASS` with no findings.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `520 passed, 60 skipped, 2 warnings` in `676.13s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `43.2s` and
  `37.6s`.
