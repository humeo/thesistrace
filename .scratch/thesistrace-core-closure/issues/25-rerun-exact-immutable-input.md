# 25 — Rerun the exact immutable input

**What to build:** Let a user create a new ResearchRun from the selected Run's
exact immutable input and Dataset Release.

**Blocked by:** 11, 20.

**Status:** ready-for-agent

- [ ] Rerun always creates a new ResearchRun ID and leaves the selected Run
  unchanged.
- [ ] The new Run copies exactly the original immutable input and Dataset
  Release, including field bindings and fixed calculation contracts.
- [ ] Current Definition edits and a newer latest Release have no effect on the
  new Run.
- [ ] Matching request replay returns the same new Run; different input with the
  same request ID conflicts.
- [ ] A structurally malformed Rerun request creates no action receipt.
- [ ] The new Run enters the ordinary queued, execution, Publication, and
  terminal lifecycle.
- [ ] The Web navigates to the new stable Run URL and preserves provenance to
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
