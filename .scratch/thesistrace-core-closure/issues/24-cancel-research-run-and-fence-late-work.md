# 24 — Cancel a ResearchRun and fence late work

**What to build:** Let a user cancel queued or running ResearchRun work without
allowing late computation or publication to change the committed outcome.

**Blocked by:** 20.

**Status:** complete

**Implementation:** complete

- [x] Cancel atomically records `cancelled` for queued or running work and
  advances its execution fence.
- [x] Any late success, failure, or Result publication is rejected after the
  cancellation commit.
- [x] If success or failure commits first, Cancel returns that existing terminal
  state and never overwrites it.
- [x] Matching request replay returns the original outcome; different action
  input with the same request ID conflicts.
- [x] A structurally malformed Cancel request creates no action receipt.
- [x] ResearchRun detail refreshes to the authoritative product state without
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

- `POST /api/research-runs/{run_id}/cancel` serializes the action by request ID
  and locks the ResearchRun before deciding the winner. Queued or running work
  atomically cancels its active Attempt, advances the Run fence, commits public
  `cancelled`, and saves the replay receipt. Missing Runs return 404 without a
  receipt; malformed bodies never enter the service; reuse of one request ID
  with different action input conflicts.
- Success, failure, and Cancel share the same Run-row serialization and fence.
  Acceptance races real worker success and failure commits against Cancel, and
  separately releases late success and late failure work after cancellation.
  Exactly the first terminal commit wins; stale lifecycle and Result publication
  writes are rejected.
- The ResearchRun page offers Cancel only for queued/running product states.
  Load and Cancel generations, AbortController lifecycle guards, and Run
  identity prevent old requests from mutating a new page. A pending Cancel
  request ID survives a lost response so Retry repeats the same logical action.
  Cancel also supersedes an in-flight Refresh and clears its loading state.
- Browser acceptance streams an old `running` response so its headers arrive
  before Cancel while its JSON body remains blocked. After Cancel returns, the
  test releases that stale body and proves the page remains authoritative
  `cancelled`, Refresh is usable, and no Attempt, fence, receipt, manifest,
  object, or worker diagnostic is exposed.
- The final ticket backend command written above passed `22 passed, 1 warning`
  in `36.45s` against real PostgreSQL and RustFS. The final Core browser command
  passed `10 passed` in `42.1s`; the command's final `down` removed the isolated
  containers.
- Independent review found and drove closure of three UI race classes: an old
  poll overwriting Cancel, a response-body window after the first generation
  check, and Refresh remaining permanently busy after Cancel. Commits
  `49dd14c`, `660cbc5`, and `9747502` added lifecycle fences and exact browser
  reproductions. Final review passed `Standards: PASS` and `Spec: PASS` with no
  blocking findings.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `521 passed, 88 skipped, 2 warnings` in `794.47s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `53.2s` and
  `47.8s`.
