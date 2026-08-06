# 07 — Run browser acceptance in a disposable full topology

**What to build:** Let the host Playwright runner exercise the accepted Core
journey against a unique, complete Test topology and leave behind evidence
rather than infrastructure when the journey fails.

**Blocked by:** 05 — Provide the Compose Watch development loop; 06 — Run
isolated real Integration Tests.

**Status:** ready-for-agent

- [ ] `pnpm test:e2e` creates a unique Test project containing Web, API, Worker,
      PostgreSQL, RustFS, and the one-shot Migration service.
- [ ] The browser runner starts only after migration and every required service
      reaches its readiness boundary.
- [ ] The host Playwright runner drives Data Update, Research Definition Save
      and Run, Result inspection, Rerun, DailyTrack start and advance, blocked
      Retry, and terminal Stop through the real Web product.
- [ ] Browser traffic cannot reach the canonical Development project or reuse
      Development data.
- [ ] The browser command reuses the canonical Test identity, safety, evidence,
      keep-environment, and teardown behavior rather than creating a second
      lifecycle implementation.
- [ ] Failure evidence includes available Playwright screenshots, recordings,
      traces, and reports grouped with Compose diagnostics under one run
      identity.
- [ ] Success leaves no Test containers, networks, or volumes behind.
- [ ] The command does not start a host Vite, API, or Worker process as an
      alternate runtime topology.
