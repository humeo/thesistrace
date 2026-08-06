# 06 — Run isolated real Integration Tests

**What to build:** Let the developer run the existing real PostgreSQL and
RustFS integration suites from the host against a fresh, uniquely identified
Test environment that always produces useful diagnostics and safe teardown.

**Blocked by:** 01 — Establish the fast host test gate; 03 — Boot the persistent
Development Core through Compose.

**Status:** ready-for-agent

- [ ] `pnpm test:integration` generates a unique Test run and Compose project
      identity for every invocation.
- [ ] Each run receives isolated ports, network, volumes, PostgreSQL data, and
      RustFS data and cannot address the canonical Development environment.
- [ ] The command validates its merged Compose configuration before creating
      resources, starts from empty data, completes migration, and waits for
      required health.
- [ ] The host-side integration and acceptance suites run against the newly
      created real PostgreSQL and pinned RustFS services.
- [ ] Cleanup is registered before Test resources are created and removes the
      Test project and volumes after success.
- [ ] Failure captures Compose status, timestamped service logs, container
      inspection, and available Pytest reports under the Test run identity
      before default cleanup.
- [ ] An explicit keep-environment switch preserves only the failing Test
      project for interactive diagnosis; the default remains cleanup.
- [ ] Cleanup refuses the Development identity and every project name outside
      the canonical Test prefix.
- [ ] Two Test identities can run or be simulated concurrently without sharing
      state or ports.
- [ ] Live Tushare and every Production-oriented check remain absent.
