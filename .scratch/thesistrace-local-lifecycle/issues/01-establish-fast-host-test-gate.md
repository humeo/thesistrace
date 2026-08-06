# 01 — Establish the fast host test gate

**What to build:** Provide the developer with one fast host-side test command
that catches inexpensive Python and Web regressions without creating or
addressing a Compose environment.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] `pnpm test` runs Ruff, TypeScript type checking, pure Kernel tests,
      architecture tests, adapter-contract tests, and Web unit tests on the
      host.
- [x] The fast command does not start, stop, reset, or connect to any Compose
      project.
- [x] The command uses the mise-pinned Node.js 24 and pnpm toolchain and the
      uv-managed Python environment.
- [x] Failures from each constituent test layer propagate as a non-zero command
      result without hiding the failing tool output.
- [x] Live Tushare, integration, acceptance, browser, Hosted, and Production
      checks are absent from the fast gate.
- [x] Existing focused test behavior remains green through the new public
      command.

## Comments

- Implemented by `3246efe build(tooling): add fast pnpm test gate`.
- Focused verification: `pnpm test` passed Ruff, 142 Python tests, TypeScript
  checking, and one Vitest test.
- Review round 1 against `3052a23`: Spec had no findings; Standards had one
  non-material duplication observation deferred to Ticket 08, where the full
  gate will compose this command.
