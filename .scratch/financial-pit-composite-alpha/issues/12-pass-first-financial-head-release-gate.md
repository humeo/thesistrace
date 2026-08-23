# 12 — Pass the first financial Head release gate

**What to build:** Prove the complete first financial-capable product from an
empty environment using deterministic source replay, real infrastructure, the
real browser, and final production images. This gate must demonstrate that the
first published financial Head is executable end to end and that its
ResearchRun, DailyTrack, refresh, blocking, recovery, performance, and
provenance claims hold together.

**Blocked by:** 11 — Expose financial Alpha and Data readiness.

**Status:** complete

- [x] A fresh isolated environment bootstraps or refreshes a deterministic
  2010-start market and financial dataset through the real private Data
  Operator.
- [x] The resulting Dataset Head contains complete Market and Financial family
  declarations and reports Financial Research Readiness.
- [x] The browser confirms Data Overview, discovery of all six fields and
  rank, submission of one mixed Composite Alpha, Worker execution, result
  publication, and DailyTrack start.
- [x] Publishing a later deterministic Generation advances the financial
  DailyTrack with exact batch-incremental equality.
- [x] A constructed Financial Coverage cutoff blocks the financial Track while
  a market-only Track advances, and a later complete Financial Refresh resumes
  the blocked Track.
- [x] Concurrent Head movement leaves already pinned ResearchRun and Tracking
  Advance results unchanged and auditable.
- [x] The committed 2010-scale I/O, memory, Pin, and GC budgets pass in the
  release environment.
- [x] The full deterministic unit, architecture, adapter, integration, Worker,
  browser, and production-image smoke gates pass from the repository's stable
  commands.
- [x] Production images install the fresh schema, start all required services,
  report readiness, execute the private operator path, and complete the
  ResearchRun-to-DailyTrack journey.
- [x] Public network requests are rejected during automated acceptance; live
  TuShare capability evidence remains a separate deployment prerequisite.
- [x] Failures preserve source shard, family, Generation, Attempt, Formula,
  field set, HTTP, service log, and browser screenshot diagnostics without
  credentials.
- [x] The final runtime contains no flat all-table Generation fallback,
  prices-only Alpha evaluator, second financial Head, ingestion-only finance
  publication, or obsolete duplicate behavioral contract.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- Verification: `bun run test` (439 Python + 25 Web), `bun run test:integration`
  (151 + database restart), `bun run test:e2e` (3 browser journeys),
  `bun run test:image-smoke`, and `bun run test:benchmark` all passed in fresh
  isolated environments.
- Final independent Spec and Standards reviews were CLEAN.
