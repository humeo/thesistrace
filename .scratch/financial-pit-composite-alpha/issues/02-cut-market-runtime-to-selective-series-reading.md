# 02 — Cut the market runtime to selective Series reading

**What to build:** Move the complete existing market research journey onto the
Family Manifest contract and a Data-owned selective Series reader in one hard
cut. Data Overview, admission, ResearchRun, and DailyTrack must keep their
observable market behavior while Claim and Pin remain metadata-only and
execution opens only the market data required by the admitted Alpha.

**Blocked by:** 01 — Materialize Family Manifest market candidates.

**Status:** ready-for-agent

- [ ] Bootstrap and Market Refresh publish the Family Manifest Generation
  contract through the single Dataset Head.
- [ ] Data Overview reports Market Coverage and readiness from descriptors
  without opening Parquet.
- [ ] ResearchRun admission validates requested dates and Field References from
  the pinned descriptors without materializing the complete Generation.
- [ ] Claim commits the running Attempt and pins one root descriptor before any
  Parquet object is opened.
- [ ] A market ResearchRun reads only the required market families, sessions,
  instruments, and fields and produces the same deterministic result as the
  retained reference behavior.
- [ ] A market DailyTrack uses the same Data-owned Series boundary and retains
  its current bounded continuation, retry, cancellation, and checkpoint
  behavior.
- [ ] An Attempt pinned to Generation A completes from A when Market Refresh
  publishes Generation B concurrently.
- [ ] The Research Kernel receives storage-independent aligned Series and has
  no physical market table or Parquet binding.
- [ ] The active runtime no longer serializes or opens the whole Canonical
  dataset as ResearchRun or DailyTrack input.
- [ ] The obsolete flat all-table runtime path and its duplicate behavioral
  tests are removed; no compatibility switch or fallback remains.
- [ ] The existing real browser market ResearchRun-to-DailyTrack journey
  remains green against a fresh store.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- This is the deliberate wide hard-cut ticket after the candidate-only
  prefactor in Ticket 01.
