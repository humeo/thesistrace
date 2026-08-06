# 07 — Run browser acceptance in a disposable full topology

**What to build:** Let the host Playwright runner exercise the accepted Core
journey against a unique, complete Test topology and leave behind evidence
rather than infrastructure when the journey fails.

**Blocked by:** 05 — Provide the Compose Watch development loop; 06 — Run
isolated real Integration Tests.

**Status:** complete

- [x] `pnpm test:e2e` creates a unique Test project containing Web, API, Worker,
      PostgreSQL, RustFS, and the one-shot Migration service.
- [x] The browser runner starts only after migration and every required service
      reaches its readiness boundary.
- [x] The host Playwright runner drives Data Update, Research Definition Save
      and Run, Result inspection, Rerun, DailyTrack start and advance, blocked
      Retry, and terminal Stop through the real Web product.
- [x] Browser traffic cannot reach the canonical Development project or reuse
      Development data.
- [x] The browser command reuses the canonical Test identity, safety, evidence,
      keep-environment, and teardown behavior rather than creating a second
      lifecycle implementation.
- [x] Failure evidence includes available Playwright screenshots, recordings,
      traces, and reports grouped with Compose diagnostics under one run
      identity.
- [x] Success leaves no Test containers, networks, or volumes behind.
- [x] The command does not start a host Vite, API, or Worker process as an
      alternate runtime topology.

## Comments

- Implemented in `6f18915` by extending the hardened Ticket 06 Test runtime
  with one E2E mode; no second identity, safety, evidence, keep, signal, or
  teardown implementation was introduced.
- Real `pnpm test:e2e` started the complete six-service Test topology, observed
  migration exit successfully and every long-running service become healthy,
  then ran all 18 Playwright scenarios successfully in 2.2 minutes.
- The run used randomly mapped API port `53766` and Web port `53649`. Host
  Playwright addressed only the Web origin; the Playwright configuration no
  longer declares host Web, API, or Worker processes.
- The HTML report was stored under the run evidence directory. Failure-path
  tests place available HTML, trace, screenshot, and video artifacts beside
  Compose status, logs, and inspection before shared cleanup.
- Exact label queries after the real success found no Test containers, network,
  or volumes. Standards and Spec reviews used fixed point `164d438` and
  reported no findings.
