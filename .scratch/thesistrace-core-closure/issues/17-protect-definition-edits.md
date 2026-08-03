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

- Run `uv run pytest -q tests/integration tests/acceptance` with concurrent
  revision updates and malformed documents; confirm rejected writes leave the
  stored Definition unchanged.
- Run `bun run --cwd web test:e2e` and confirm conflict recovery retains the
  submitted editor state for correction.

## Comments
