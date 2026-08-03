# 18 — Reject a non-runnable Run while saving the Definition

**What to build:** Let Run save the current editor content and return actionable
issues without creating a ResearchRun when the saved content is not runnable.

**Blocked by:** 17.

**Status:** ready-for-agent

- [ ] The Web sends current content directly through Run and never sequences a
  separate client-side Save first.
- [ ] A semantically rejected Run commits exactly one new Definition revision
  and a rejected action receipt.
- [ ] Rejection creates no immutable Run input and no ResearchRun.
- [ ] Matching request replay returns the original revision and issues without
  another write; conflicting fingerprint reuse returns a conflict.
- [ ] A structurally malformed Run request writes neither Definition, receipt,
  immutable input, nor ResearchRun.
- [ ] Missing hypothesis alone never causes rejection.
- [ ] The editor displays the saved revision and actionable validation issues.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with rejected,
  replayed, conflicting, and structurally malformed Run requests.
- Run `bun run --cwd web test:e2e` and confirm rejection saves once, displays
  issues, and leaves the ResearchRun list unchanged.

## Comments
