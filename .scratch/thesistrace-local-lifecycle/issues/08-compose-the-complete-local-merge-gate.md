# 08 — Compose the complete local merge gate

**What to build:** Give the maintainer one complete local command that fails
fast on inexpensive regressions, then proves real integration and the browser
journey with deterministic cleanup before code is merged.

**Blocked by:** 01 — Establish the fast host test gate; 06 — Run isolated real
Integration Tests; 07 — Run browser acceptance in a disposable full topology.

**Status:** complete

- [x] `pnpm check` runs the fast host gate, isolated Integration Test gate, and
      disposable browser gate in increasing cost order.
- [x] A failure in any layer returns a non-zero result and prevents later,
      unnecessary layers from running.
- [x] Any Test environment already created by a failing layer follows the
      canonical evidence and cleanup contract.
- [x] A successful complete gate leaves no canonical Test project, network,
      volume, or temporary port allocation behind.
- [x] The complete gate never starts, stops, resets, or reads canonical
      Development data.
- [x] Live Tushare, Hosted, login, tenancy, Staging, Production, deployment,
      release-image, backup, and rollback work remain outside the command.
- [x] Architecture tests treat the pnpm command contract and Compose topology
      as the active lifecycle boundary and reject restoration of Makefile or
      hybrid host application startup.
- [x] Running each constituent command independently and through `pnpm check`
      yields the same externally observable acceptance result.

## Comments

- Implemented in `daf1f90` by defining `pnpm check` as the fail-fast sequence
  `pnpm test && pnpm test:integration && pnpm test:e2e`, then removing the
  legacy fixed-port `core-test-runtime` and `compose.test.yaml` entrypoints.
- Focused architecture verification passed all 61 tests. Architecture
  contracts now reject Makefile, the retired runner/overlay, Development
  project selection from Test, and host API, Worker, or Vite startup in the
  active merge gate.
- Two complete-gate failure runs exposed nondeterministic assertions in the
  final browser scenario. Both stopped with non-zero status, retained
  Playwright and Compose evidence, and removed their exact Test containers,
  networks, and volumes. Fixes `ef4a492` and `566b099` model the valid Worker
  claim race and replace fixed delays with explicit Playwright request gates.
- Final `CI=true mise exec -- pnpm check` at `566b099` passed the fast layer
  (`176` Python tests, TypeScript, and Web shell), Integration (`102` tests),
  and browser acceptance (`18` tests). The Integration and E2E run metadata
  both recorded `cleanup_status=0` and `status=0`.
- Post-gate Docker label queries found no `thesistrace-test-*` containers,
  networks, or volumes. All six canonical Development container IDs matched
  the pre-gate snapshot and its long-running services remained healthy.
- Standards and Spec reviews used fixed point `9fa751c`; three review rounds,
  including both runtime-discovered E2E fixes, reported no findings.
