# 02 — Cut the market runtime to selective Series reading

**What to build:** Move the complete existing market research journey onto the
Family Manifest contract and a Data-owned selective Series reader in one hard
cut. Data Overview, admission, ResearchRun, and DailyTrack must keep their
observable market behavior while Claim and Pin remain metadata-only and
execution opens only the market data required by the admitted Alpha.

**Blocked by:** 01 — Materialize Family Manifest market candidates.

**Status:** complete

- [x] Bootstrap and Market Refresh publish the Family Manifest Generation
  contract through the single Dataset Head.
- [x] Data Overview reports Market Coverage and readiness from descriptors
  without opening Parquet.
- [x] ResearchRun admission validates requested dates and Field References from
  the pinned descriptors without materializing the complete Generation.
- [x] Claim commits the running Attempt and pins one root descriptor before any
  Parquet object is opened.
- [x] A market ResearchRun reads only the required market families, sessions,
  instruments, and fields and produces the same deterministic result as the
  retained reference behavior.
- [x] A market DailyTrack uses the same Data-owned Series boundary and retains
  its current bounded continuation, retry, cancellation, and checkpoint
  behavior.
- [x] An Attempt pinned to Generation A completes from A when Market Refresh
  publishes Generation B concurrently.
- [x] The Research Kernel receives storage-independent aligned Series and has
  no physical market table or Parquet binding.
- [x] The active runtime no longer serializes or opens the whole Canonical
  dataset as ResearchRun or DailyTrack input.
- [x] The obsolete flat all-table runtime path and its duplicate behavioral
  tests are removed; no compatibility switch or fallback remains.
- [x] The existing real browser market ResearchRun-to-DailyTrack journey
  remains green against a fresh store.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- This is the deliberate wide hard-cut ticket after the candidate-only
  prefactor in Ticket 01.
- Bootstrap, refresh, Head, overview, admission, ResearchRun, and DailyTrack now
  use the one Family Manifest Generation contract. Claim/Pin read descriptors
  only; transaction-level acceptance tests prove ResearchRun and DailyTrack
  Attempts are committed before selected Parquet objects open.
- Data reads only requested session partitions, Universe instruments, Alpha
  fields, execution columns, and required auxiliary columns, then provides the
  Kernel with storage-independent `AlignedResearchData`. The flat all-table
  Head/runtime and Canonical Kernel adapter were deleted without fallback.
- Verification: `pnpm test` passed `317` Python tests plus frontend typecheck
  and `9` tests; `pnpm test:integration` passed `117` tests plus the database
  restart test; `pnpm test:e2e` passed the fresh-container browser
  ResearchRun-to-DailyTrack journey.
- Standards and Spec reviews ran independently through two closure rounds. All
  findings were fixed; both final re-reviews reported CLEAN.
