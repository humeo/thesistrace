# 01 — Establish the fast host test gate

**What to build:** Provide the developer with one fast host-side test command
that catches inexpensive Python and Web regressions without creating or
addressing a Compose environment.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `pnpm test` runs Ruff, TypeScript type checking, pure Kernel tests,
      architecture tests, adapter-contract tests, and Web unit tests on the
      host.
- [ ] The fast command does not start, stop, reset, or connect to any Compose
      project.
- [ ] The command uses the mise-pinned Node.js 24 and pnpm toolchain and the
      uv-managed Python environment.
- [ ] Failures from each constituent test layer propagate as a non-zero command
      result without hiding the failing tool output.
- [ ] Live Tushare, integration, acceptance, browser, Hosted, and Production
      checks are absent from the fast gate.
- [ ] Existing focused test behavior remains green through the new public
      command.
