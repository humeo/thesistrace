# 05 — Rebuild a complete Financial Refresh candidate

**What to build:** Make one manual V1 Financial Refresh attempt rebuild the
complete historical financial family candidate from the expected
endpoint-by-instrument shards. It must resume safely, detect every
source-visible change under one completeness rule, retain previously accepted
versions, and produce either one fully validated candidate or an explicit
failure without publishing partial state.

**Blocked by:** 04 — Materialize the 2010 Point-in-Time Financial candidate.

**Status:** ready-for-agent

- [ ] A Financial Refresh attempt calculates the complete current historical
  ordinary A-share shard set for income, balance-sheet, and cash-flow endpoints.
- [ ] Newly listed, delisted, and no-longer-active instruments are handled by
  the same expected-shard rule rather than an active-only shortcut.
- [ ] Interrupted attempts resume from durable completed-shard checkpoints.
- [ ] Exact duplicate Raw Financial Batches, Canonical rows, partitions, and
  family Manifests reuse their existing content identities.
- [ ] Newly returned source versions and observed corrections append to the
  candidate.
- [ ] A previously accepted source version remains referenced when a later
  TuShare response no longer contains it.
- [ ] Source absence never acts as a deletion instruction.
- [ ] Permission, truncation, schema, checkpoint, mapping, Coverage, or
  cross-family validation failure prevents a complete candidate.
- [ ] Partial endpoint or instrument success remains unpublished and is
  distinguishable from successful candidate completion.
- [ ] Progress exposes expected, completed, failed, and resumed shard counts
  plus bounded phase timings without sensitive credentials.
- [ ] V1 has no recent-announcement window, rotating reconciliation, VIP
  transport, automatic schedule, or provider fallback.
- [ ] The completed attempt returns one validated financial family candidate
  for later atomic composition but does not move the Dataset Head in this
  ticket.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- Atomic Head publication is intentionally deferred until ResearchRun,
  DailyTrack, and performance readiness exist.
