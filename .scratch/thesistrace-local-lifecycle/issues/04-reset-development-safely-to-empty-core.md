# 04 — Reset Development safely to an empty Core

**What to build:** Give the developer one explicit reset command that can erase
only the canonical Development state and return the product to a migrated empty
state without risking any unrelated environment.

**Blocked by:** 03 — Boot the persistent Development Core through Compose.

**Status:** complete

- [x] `pnpm dev:reset` validates the exact canonical Development project
      identity before issuing any destructive Compose operation.
- [x] The reset command refuses empty, malformed, Test, Production-like, and
      unrelated project identities before deleting containers, volumes, or
      local state.
- [x] A successful reset removes only canonical Development data, recreates the
      environment, completes migration, and waits for health.
- [x] After reset, the Web and HTTP interface expose the canonical empty Core
      with no Dataset Release, Research Definition, ResearchRun, or DailyTrack.
- [x] Reset does not automatically execute Data Update or publish Fixture data.
- [x] Ordinary `pnpm dev:up` and `pnpm dev:stop` never invoke destructive reset
      behavior.
- [x] Safety tests exercise all accepted and rejected project-identity classes
      through the public reset command.

## Comments

- Implemented in `3170aee`; public-command review coverage fixed in `a4512d8`.
- Verified the public pnpm command rejects empty, Test, Production-like,
  malformed, and unrelated identities before reaching Compose.
- Live reset removed the canonical Development volumes, reran migration, waited
  for health, and returned all four HTTP resources plus the browser Data view to
  an empty state without automatic publication.
- Two review rounds used the fixed point `61525f0`; final Standards and Spec
  reviews reported no findings.
