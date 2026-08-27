# 04 — Verify and cut over the CSI 300 Benchmark contract

**What to build:** Finish the development hard cut, qualify the production-shaped
system, and initialize the preserved Development Dataset Head's Benchmark
Snapshot with one ordinary live Market Refresh.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] Data Overview reports Benchmark readiness, Coverage, Snapshot SHA-256, and last publication time.
- [ ] All selected-universe/equal-weight benchmark fields, functions, contracts, fixtures, tests, and UI labels are absent with no compatibility, migration, or fallback.
- [ ] Glossary, ADR index, architecture, operator and local lifecycle runbooks, and all four tickets match the independent Store.
- [ ] `mise exec -- pnpm check:release` passes at final branch HEAD, including Production Image qualification.
- [ ] A real browser completes a Strategy ResearchRun and DailyTrack and verifies the fixed comparison.
- [ ] Before Development reset, record exact containers, Product volumes, Canonical volume, and Dataset Head.
- [ ] Run `dev:reset` exactly once; preserve Canonical Data and Benchmark volumes and do not run `dev:erase`.
- [ ] Start the new version and run one ordinary live Market Refresh; do not run Dataset Bootstrap.
- [ ] Verify no Canonical Benchmark Family exists and Snapshot covers 2010-01-04 through current Market Coverage.
