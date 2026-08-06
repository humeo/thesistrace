# 08 — Compose the complete local merge gate

**What to build:** Give the maintainer one complete local command that fails
fast on inexpensive regressions, then proves real integration and the browser
journey with deterministic cleanup before code is merged.

**Blocked by:** 01 — Establish the fast host test gate; 06 — Run isolated real
Integration Tests; 07 — Run browser acceptance in a disposable full topology.

**Status:** ready-for-agent

- [ ] `pnpm check` runs the fast host gate, isolated Integration Test gate, and
      disposable browser gate in increasing cost order.
- [ ] A failure in any layer returns a non-zero result and prevents later,
      unnecessary layers from running.
- [ ] Any Test environment already created by a failing layer follows the
      canonical evidence and cleanup contract.
- [ ] A successful complete gate leaves no canonical Test project, network,
      volume, or temporary port allocation behind.
- [ ] The complete gate never starts, stops, resets, or reads canonical
      Development data.
- [ ] Live Tushare, Hosted, login, tenancy, Staging, Production, deployment,
      release-image, backup, and rollback work remain outside the command.
- [ ] Architecture tests treat the pnpm command contract and Compose topology
      as the active lifecycle boundary and reject restoration of Makefile or
      hybrid host application startup.
- [ ] Running each constituent command independently and through `pnpm check`
      yields the same externally observable acceptance result.
