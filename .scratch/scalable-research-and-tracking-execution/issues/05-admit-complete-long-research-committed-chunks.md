# 05 — Admit and complete long Research through committed Chunks

**What to build:** Let a researcher run a valid Alpha from 2010 through the latest
covered Research Session without total-work rejection or unbounded memory. Admission
freezes a peak-capacity Chunk plan, the one supervised child executes every Chunk in
order, committed progress becomes visible, and completion publishes one exact atomic
Result.

**Blocked by:** 04 — Confirm Research cancellation after child exit

**Status:** complete

- [x] Estimated Total Research Work is retained for progress, duration guidance, warnings, and telemetry but no longer rejects a Run or changes queue priority.
- [x] Admission rejects only structural, lookback, coverage, or minimum legal peak-footprint failures relevant to this execution change.
- [x] The deterministic planner selects the largest fixed Chunk size from 1 through 63 sessions that fits the 1.5-GiB execution budget and is estimated within the 30-second sizing target.
- [x] One complete eligible full-Universe session that fits memory remains admissible even when its estimate exceeds 30 seconds; the frozen plan records the exceeded target.
- [x] Inability to fit one complete full-Universe session produces a specific capacity admission issue and creates no Run.
- [x] The ordered Calculation Warm-up and Research Period are partitioned into contiguous Chunks at the frozen fixed size, with only the final Chunk allowed to be shorter.
- [x] Instrument sharding, runtime Chunk shrinking, alternate-Generation selection, and adaptive replanning are absent.
- [x] The same execution child processes all Chunks sequentially and starts the next Chunk only after the supervisor acknowledges the committed boundary.
- [x] Cross-Chunk continuation contains only bounded rolling tails, unmatured 1-, 5-, and 20-session Label inputs, ordered Factor aggregate state, Strategy account and scheduling state, and checksum state.
- [x] Completed Alpha cross-sections, matured stock-level Labels, and daily Factor observations are folded into bounded state and released before the next Chunk.
- [x] Growing Strategy Daily Observations are streamed to ordered immutable Staged Result Partitions rather than accumulated as one full-period Python payload.
- [x] Each complete Chunk commits one private immutable execution boundary and atomically advances durable ResearchRun Progress.
- [x] Warm-up progress is visible separately and never increments completed Research Period sessions.
- [x] Transient heartbeat phase and current session never count as committed work.
- [x] After sufficient committed Chunks, any displayed remaining duration is labelled as a revisable estimate rather than an SLA.
- [x] Chunked and uninterrupted Alpha, Factor, Strategy, terminal state, missingness, decimal values, and canonical binary64 serialization are exactly equivalent.
- [x] Finalization does not recompute completed Chunks or combine approximate summaries and atomically publishes exactly one immutable Result Bundle.
- [x] Public and browser views show committed versus in-flight progress but expose no private Checkpoints, staged objects, provisional observations, or provisional metrics.
- [x] A deterministic 2010-to-latest functional fixture completes through multiple Chunks for market, financial, and composite Formulae within bounded memory.
- [x] No Polars, DuckDB, SQL executor, V2 engine, compatibility path, or duplicate Alpha evaluator is introduced.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 04.
