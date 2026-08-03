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

- Run `uv run pytest -q tests/integration tests/acceptance` with queued cancel,
  running cancel, terminal-state races, replay, conflict, and stale publication.
- Run `bun run --cwd web test:e2e` and confirm Cancel becomes visible before the
  deliberately delayed worker finishes and remains authoritative afterward.

## Comments
