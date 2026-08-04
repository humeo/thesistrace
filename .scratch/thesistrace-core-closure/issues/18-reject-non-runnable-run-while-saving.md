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
