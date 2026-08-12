# 08 — Advance, block, and resume financial DailyTracks

**What to build:** Continue a successful Composite Alpha ResearchRun through
DailyTrack using exactly the same financial Series semantics, cs_rank behavior,
and Numeric Execution Contract. The Track must advance only through covered
sessions, explain and preserve a financial-readiness block, and resume after a
later complete financial Generation without rewriting prior checkpoints.

**Blocked by:** 07 — Run a cs_rank Composite Alpha ResearchRun.

**Status:** ready-for-agent

- [ ] Starting a DailyTrack from a successful market-financial ResearchRun
  freezes the complete seed input, Field References, Formula, and calculation
  contracts.
- [ ] Tracking Advance uses the same Data-owned Series reader, financial
  point-in-time rules, Series Execution Plan, Builtin Definitions, and numeric
  behavior as the seed ResearchRun.
- [ ] A Track advance reads only bounded Effective Alpha Lookback state plus
  the new target Research Sessions.
- [ ] Reference batch execution and session-by-session Tracking Advance produce
  exactly equal Alpha, ranking, and retained Strategy outcomes for the same
  inputs.
- [ ] A financial Track blocks before the first target session beyond the
  financial observation-through cutoff.
- [ ] The blocked state identifies Financial Coverage as the readiness reason
  and preserves the last authoritative Tracking Checkpoint.
- [ ] After a complete later financial Generation advances the cutoff, the
  blocked Track resumes and catches up without changing its Formula or
  historical checkpoints.
- [ ] A market-only DailyTrack advances through the same market sessions even
  when Financial Coverage is behind or Financial Refresh has failed.
- [ ] Each Tracking Advance Attempt pins one complete Data Generation and never
  joins independently moving family Heads.
- [ ] Retry, duplicate claim, cancellation, crash recovery, and publication
  remain idempotent for financial Tracks.
- [ ] A later observed financial correction never rewrites an already
  published Tracking Checkpoint.
- [ ] Deterministic integration tests cover cutoff blocking, refresh recovery,
  market-only independence, and batch-incremental equality.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
