# 17 — Protect Definition edits with revision and structure checks

**What to build:** Prevent concurrent or malformed edits from corrupting a
saved Research Definition while preserving the user's current editor content.

**Blocked by:** 16.

**Status:** complete

**Implementation:** complete

- [x] Updating an existing Definition requires its current expected revision.
- [x] A revision mismatch changes nothing and returns the authoritative current
  revision.
- [x] Unknown properties, wrong structural types, invalid expression shape, and
  invalid operator arity or operand types are rejected without a write.
- [x] Two concurrent edits cannot both advance the same revision.
- [x] A successful edit advances revision exactly once and may change the
  generated name or any allowed authoring field.
- [x] The Web reports conflicts and structural errors without discarding the
  user's unsaved content.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_definition_edit_protection.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must exercise two edits against the same revision and malformed
expression documents, then prove every rejected request left the authoritative
Definition unchanged. The browser must force a real revision conflict and prove
the user's submitted editor values remain visible for correction.

## Comments

- Definition commands now use strict Pydantic types and enforce revision,
  holdings-count, and rebalance bounds. Unknown fields, coercible wrong types,
  out-of-range values, and non-object Alpha values fail before service code.
- The composition root injects Kernel's normalized Alpha validator with
  Data-owned field bindings. Definition create/update invokes it before opening
  any write transaction, so unknown fields/operators, malformed nodes, bad
  arity, operand-type errors, and invalid windows write nothing.
- The concurrency acceptance holds the target row from an independent
  transaction, launches two independent HTTP runtimes, and waits until
  PostgreSQL reports both application `SELECT ... FOR UPDATE` statements as
  lock waiters. Releasing the lock yields exactly one revision-2 success and
  one 409 carrying authoritative revision `2`.
- The Web separates load, save, and conflict errors. A conflict preserves every
  editor value and offers only an explicitly destructive “Discard my edits and
  load server version” action. Structural/save errors hide Retry and Refresh;
  the user corrects the existing values and Save succeeds without a reload.
- Core browser verification initially exposed a pre-existing Data update timing
  race. The Data page now enters `updating` immediately after the click and
  restores its previous overview if POST fails; the real three-update test has
  a 90-second budget. This does not add a second data path.
- The final ticket backend command passed `81 passed, 1 warning` in `214.27s`.
  The final Core browser command passed `4 passed` in `26.5s`, including real
  409 and 422 responses, explicit conflict discard, preserved invalid content,
  correction, and successful Save to revision `3`.
- Independent review found and closed two false-positive acceptance gaps: Save
  errors shared a destructive GET Retry/Refresh path, and the original thread
  test did not prove transaction overlap. Final independent review passed
  `Standards: PASS` and `Spec: PASS` with no findings.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `518 passed, 53 skipped, 2 warnings`, Web typecheck/build passed, and
  narrow/desktop Playwright passed in `35.3s` and `34.2s`.
