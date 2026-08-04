# 25 — Rerun the exact immutable input

**What to build:** Let a user create a new ResearchRun from the selected Run's
exact immutable input and Dataset Release.

**Blocked by:** 11, 20.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Rerun always creates a new ResearchRun ID and leaves the selected Run
  unchanged.
- [x] The new Run copies exactly the original immutable input and Dataset
  Release, including field bindings and fixed calculation contracts.
- [x] Current Definition edits and a newer latest Release have no effect on the
  new Run.
- [x] Matching request replay returns the same new Run; different input with the
  same request ID conflicts.
- [x] A structurally malformed Rerun request creates no action receipt.
- [x] The new Run enters the ordinary queued, execution, Publication, and
  terminal lifecycle.
- [x] The Web navigates to the new stable Run URL and preserves provenance to
  the selected original Run without presenting a comparison feature.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_research_run_rerun.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS to create and execute an original
Run, edit its Definition, publish a newer Dataset Release, and Rerun the
selected original. They must prove a distinct new Run ID, byte-equivalent
immutable input, the exact original Dataset Release, unchanged original state
and Result, persisted selected-Run provenance, ordinary execution and Result
Publication, same-request replay, different-input conflict, missing-Run 404,
and zero receipt for malformed input. The browser must start from the original
Run detail, navigate to the new stable Run URL, show its link back to the
selected original Run, and expose no comparison feature or execution mechanics.

## Comments

- `POST /api/research-runs/{run_id}/rerun` creates one new queued ResearchRun.
  A single PostgreSQL `INSERT ... SELECT` copies the selected Run's stored
  Definition identity and revision, Dataset Release, and complete
  `immutable_input`; it never reads the current Definition or latest Release.
  The selected Run is not updated.
- `rerun_of_id` durably records the directly selected source Run. The new Run
  uses the existing claim, kernel execution, Result Publication, and terminal
  lifecycle; Result provenance therefore has a new ResearchRun ID while its
  immutable-input digest, Dataset Release, calculation contracts, and semantic
  versions remain the same.
- Rerun and its receipt commit in one transaction. A transaction-level advisory
  lock serializes each request ID; matching replay returns the same new Run,
  reuse against another selected Run conflicts, missing Runs create no receipt,
  and structurally invalid bodies never enter the service.
- The Web shows Rerun only for terminal Runs, preserves the request ID after a
  lost response, fences stale load/action writes, navigates to the new stable
  Run URL, and shows a direct `Rerun of` link. It does not introduce Run
  comparison or expose Attempt, fence, receipt, manifest, object, or worker
  mechanics.
- The final ticket backend command written above passed `16 passed, 1 warning`
  in `18.07s` against real PostgreSQL and RustFS. The final Core browser command
  passed `11 passed` in `49.3s`; the command's final `down` removed the isolated
  containers.
- Independent review passed `Standards: PASS` and `Spec: PASS` with no
  findings. It confirmed the atomic exact copy, direct selected-Run provenance,
  replay/conflict serialization, ordinary execution path, UI lifecycle guards,
  and ticket coverage.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `521 passed, 89 skipped, 2 warnings` in `714.58s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `46.3s` and
  `48.8s`.
