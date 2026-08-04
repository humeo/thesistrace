# 17 — Protect Definition edits with revision and structure checks

**What to build:** Prevent concurrent or malformed edits from corrupting a
saved Research Definition while preserving the user's current editor content.

**Blocked by:** 16.

**Status:** ready-for-agent

- [ ] Updating an existing Definition requires its current expected revision.
- [ ] A revision mismatch changes nothing and returns the authoritative current
  revision.
- [ ] Unknown properties, wrong structural types, invalid expression shape, and
  invalid operator arity or operand types are rejected without a write.
- [ ] Two concurrent edits cannot both advance the same revision.
- [ ] A successful edit advances revision exactly once and may change the
  generated name or any allowed authoring field.
- [ ] The Web reports conflicts and structural errors without discarding the
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
