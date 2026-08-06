# 06 — Run isolated real Integration Tests

**What to build:** Let the developer run the existing real PostgreSQL and
RustFS integration suites from the host against a fresh, uniquely identified
Test environment that always produces useful diagnostics and safe teardown.

**Blocked by:** 01 — Establish the fast host test gate; 03 — Boot the persistent
Development Core through Compose.

**Status:** complete

- [x] `pnpm test:integration` generates a unique Test run and Compose project
      identity for every invocation.
- [x] Each run receives isolated ports, network, volumes, PostgreSQL data, and
      RustFS data and cannot address the canonical Development environment.
- [x] The command validates its merged Compose configuration before creating
      resources, starts from empty data, completes migration, and waits for
      required health.
- [x] The host-side integration and acceptance suites run against the newly
      created real PostgreSQL and pinned RustFS services.
- [x] Cleanup is registered before Test resources are created and removes the
      Test project and volumes after success.
- [x] Failure captures Compose status, timestamped service logs, container
      inspection, and available Pytest reports under the Test run identity
      before default cleanup.
- [x] An explicit keep-environment switch preserves only the failing Test
      project for interactive diagnosis; the default remains cleanup.
- [x] Cleanup refuses the Development identity and every project name outside
      the canonical Test prefix.
- [x] Two Test identities can run or be simulated concurrently without sharing
      state or ports.
- [x] Live Tushare and every Production-oriented check remain absent.

## Comments

- Implemented in `d0d27bd`; process-group, cleanup-identity, cleanup-status,
  and concurrent-isolation review fixes landed in `33eeaa5`.
- A real failure run passed 101 of 102 tests, retained JUnit plus Compose status,
  timestamped logs, and container inspection under one run identity, then
  removed its containers, network, and volumes. The failure exposed and fixed
  one stale test assumption about implicit migration startup.
- The succeeding real run passed all 102 integration and acceptance tests in
  904.51 seconds using unique ports `57841` and `57840`; exact label queries
  found no remaining Test containers, network, or volumes, while Development
  remained healthy.
- A real Ctrl-C probe forwarded the signal to the Pytest process group,
  captured available infrastructure evidence, recorded `cleanup_status=0` and
  `status=130`, and left no Test resources. Focused tests also cover TERM,
  cleanup failure reporting, failing-only keep behavior, and two simultaneous
  simulated runs with disjoint ports, resource names, state directories, and
  buckets.
- Two review rounds used the fixed point `43ffda7`; final Standards and Spec
  reviews reported no findings.
