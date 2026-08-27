# 04 — Verify and cut over the CSI 300 Benchmark contract

**What to build:** Finish the development hard cut, qualify the production-shaped
system, and initialize the preserved Development Dataset Head's Benchmark
Snapshot with one ordinary live Market Refresh.

**Blocked by:** 03.

**Status:** complete

- [x] Data Overview reports Benchmark readiness, Coverage, Snapshot SHA-256, and last publication time.
- [x] All selected-universe/equal-weight benchmark fields, functions, contracts, fixtures, tests, and UI labels are absent with no compatibility, migration, or fallback.
- [x] Glossary, ADR index, architecture, operator and local lifecycle runbooks, and all four tickets match the independent Store.
- [x] `mise exec -- pnpm check:release` passes at final branch HEAD, including Production Image qualification.
- [x] A real browser completes a Strategy ResearchRun and DailyTrack and verifies the fixed comparison.
- [x] Before Development reset, record exact containers, Product volumes, Canonical volume, and Dataset Head.
- [x] Run `dev:reset` exactly once; preserve Canonical Data and Benchmark volumes and do not run `dev:erase`.
- [x] Start the new version and run one ordinary live Market Refresh; do not run Dataset Bootstrap.
- [x] Verify no Canonical Benchmark Family exists and Snapshot covers 2010-01-04 through current Market Coverage.

## Comments

- Data Overview now reports independent Benchmark readiness, Coverage,
  Snapshot SHA-256, and publication time. API runtime alone constructs this
  read model; Research, Batch Research, and Tracking Workers neither mount nor
  open the Benchmark Store. Architecture and operator/local lifecycle runbooks
  describe the same hard-cut contract with no compatibility, migration, Raw
  Benchmark API, alternate index, carry, or runtime remote fallback.
- Development cutover recorded 8 containers, the three Product volumes, the
  preserved `thesistrace-dev_canonical-data` volume created
  `2026-08-15T00:14:25+09:00`, and pre-reset Head Generation manifest
  `250b591533e7e80f14b1fd34b249f7de399167c9d65680b3e45951a02c449faf`.
  Exactly one `dev:reset` was run. No `dev:erase` or Development Dataset
  Bootstrap was run. The ordinary live Market Refresh operation
  `refresh:6b37e4d5e7c26800769f276902dab9be` published the new Market Head and
  the complete Snapshot.
- The preserved Development Head is now
  `3bc1e66cdfe2dd11721965925a4514868568b1dcfd388cce6db3ffce5c7d96b4`,
  with 4,044 sessions from 2010-01-04 through 2026-08-27. The independent
  Snapshot has the same 4,044-session Coverage and SHA-256
  `7b4e3478d03dcd6fa62d6adce593011b04a2a11167c34c4be6c8d449d3e6c56e`.
  The 11 Canonical Families were enumerated and contain no Benchmark Family.
- Real-browser acceptance completed Strategy ResearchRun
  `run_49e1f6cecc9443d69d70` and DailyTrack
  `track_0870f2a1ec2c4a9eb11a`. Both showed the same seed Entry Open,
  Initial Cash, Snapshot identity, and Net Strategy/沪深300/Net Excess curves;
  browser console errors were empty.
- Current working-tree verification: `mise exec -- pnpm test` passed 685
  backend tests, TypeScript typecheck, and 63 frontend tests; 77 focused
  Snapshot/lifecycle/Image qualification tests passed. Isolated Compose run
  `20260827t214314z-19653-edaf3bab` passed 294 integration tests plus all six
  restart/recovery sentinels. Spec and Standards re-reviews are clean.
- Production Image Smoke run `20260827t222133z-30019-823f3a85` passed with
  final backend/Web images, full Benchmark replay, a real mounted Dataset
  outage, Worker loss, checkpoint/restart/reset recovery, and observability
  qualification. The final branch Head is qualified again by the release gate.
- `dev:up` rebuilt Development from the cutover code without another reset.
  All seven current services are healthy or running. The Canonical volume still
  has creation time `2026-08-15T00:14:25+09:00`; the Head identity is
  `b1bf0e6955ea2939625223da752df484353b1018e83985436f849e069db4cdfe`,
  the Snapshot file hash equals its declared SHA-256, and `/api/data` reports
  Benchmark readiness with the same Coverage and publication time.
