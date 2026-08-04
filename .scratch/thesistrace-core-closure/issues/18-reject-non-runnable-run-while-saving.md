# 18 — Reject a non-runnable Run while saving the Definition

**What to build:** Let Run save the current editor content and return actionable
issues without creating a ResearchRun when the saved content is not runnable.

**Blocked by:** 17.

**Status:** ready-for-agent

**Implementation:** complete

- [x] The Web sends current content directly through Run and never sequences a
  separate client-side Save first.
- [x] A semantically rejected Run commits exactly one new Definition revision
  and a rejected action receipt.
- [x] Rejection creates no immutable Run input and no ResearchRun.
- [x] Matching request replay returns the original revision and issues without
  another write; conflicting fingerprint reuse returns a conflict.
- [x] A structurally malformed Run request writes neither Definition, receipt,
  immutable input, nor ResearchRun.
- [x] Missing hypothesis alone never causes rejection.
- [x] The editor displays the saved revision and actionable validation issues.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_definition_run_rejection.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must distinguish structural rejection from semantic Run
rejection, prove the latter saves exactly one revision and receipt but creates
no immutable input or ResearchRun, and cover replay plus fingerprint conflict.
The browser must send one Run action with the current editor content, display
the saved revision and actionable issues, and leave Research Runs empty.

## Comments

- Definitions owns `run_receipts`, including request fingerprint, frozen saved
  revision/content, outcome, and actionable issues. A rejected Run writes the
  Definition revision and receipt in one PostgreSQL transaction; no
  `research_runs` schema or immutable-input record exists in this ticket.
- The transaction takes a request-scoped advisory lock before receipt lookup,
  so concurrent matching requests replay one outcome and conflicting reuse
  returns request-id 409. Existing Definition revision locking remains a
  separate guard.
- Data resolves the latest Release using the caller's concrete
  `PostgresTransaction`; Data retains its SQL ownership while Definition avoids
  nested pool acquisition. The order is request lock/receipt, Definition
  lock+Save, same-transaction Release resolution, then receipt.
- Structural validation happens before any transaction write. Semantic issues
  cover Alpha, Universe, neutralization, holdings count, rebalance interval,
  and missing Dataset Release; hypothesis is never an issue. Receipt replay is
  checked before current Release state, so later Data publication does not
  change the original outcome.
- The Web sends exactly one Run POST with current editor content. It updates the
  editor from the authoritative saved Definition and renders the issue list.
  An uncertain network/5xx result retains the logical Run request ID; content,
  revision, or Definition identity changes create a new ID, while 200/409/422
  terminate the old attempt.
- The final ticket backend command passed `82 passed, 1 warning` in `238.82s`.
  The final Core browser command passed `6 passed` in about `1.1m`, including a
  response dropped only after server commit and same-request replay to revision
  `1`.
- Independent review found and closed request-id concurrency 500/revision
  conflicts, nested connection-pool deadlock risk, and Web retry IDs changing
  after uncertain outcomes. Final review passed `Standards: PASS` and
  `Spec: PASS` with no findings.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `518 passed, 55 skipped, 2 warnings`, Web typecheck/build passed, and
  narrow/desktop Playwright passed in `34.1s` and `34.8s`.
