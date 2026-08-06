# 04 — Reset Development safely to an empty Core

**What to build:** Give the developer one explicit reset command that can erase
only the canonical Development state and return the product to a migrated empty
state without risking any unrelated environment.

**Blocked by:** 03 — Boot the persistent Development Core through Compose.

**Status:** ready-for-agent

- [ ] `pnpm dev:reset` validates the exact canonical Development project
      identity before issuing any destructive Compose operation.
- [ ] The reset command refuses empty, malformed, Test, Production-like, and
      unrelated project identities before deleting containers, volumes, or
      local state.
- [ ] A successful reset removes only canonical Development data, recreates the
      environment, completes migration, and waits for health.
- [ ] After reset, the Web and HTTP interface expose the canonical empty Core
      with no Dataset Release, Research Definition, ResearchRun, or DailyTrack.
- [ ] Reset does not automatically execute Data Update or publish Fixture data.
- [ ] Ordinary `pnpm dev:up` and `pnpm dev:stop` never invoke destructive reset
      behavior.
- [ ] Safety tests exercise all accepted and rejected project-identity classes
      through the public reset command.
