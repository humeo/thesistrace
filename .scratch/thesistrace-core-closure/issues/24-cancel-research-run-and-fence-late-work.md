# 24 — Cancel a ResearchRun and fence late work

**What to build:** Let a user cancel queued or running ResearchRun work without
allowing late computation or publication to change the committed outcome.

**Blocked by:** 20.

**Status:** ready-for-agent

- [ ] Cancel atomically records `cancelled` for queued or running work and
  advances its execution fence.
- [ ] Any late success, failure, or Result publication is rejected after the
  cancellation commit.
- [ ] If success or failure commits first, Cancel returns that existing terminal
  state and never overwrites it.
- [ ] Matching request replay returns the original outcome; different action
  input with the same request ID conflicts.
- [ ] A structurally malformed Cancel request creates no action receipt.
- [ ] ResearchRun detail refreshes to the authoritative product state without
  showing worker diagnostics.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_research_run_cancel.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS to cancel queued and genuinely
running work, pause a stale worker before publication, and race Cancel against
success and failure commits. They must prove atomic `cancelled` plus fence
advance, no late Result or lifecycle write, terminal-winner preservation,
same-request replay, different-input conflict, and zero receipt for malformed
input. The browser must observe Cancel before a delayed worker is released,
refresh the same ResearchRun to authoritative `cancelled`, and expose no
Attempt, fence, receipt, worker diagnostic, manifest, or object detail.

## Comments
