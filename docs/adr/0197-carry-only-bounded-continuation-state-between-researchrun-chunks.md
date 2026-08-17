---
status: accepted
---

# Carry only bounded continuation state between ResearchRun chunks

After a ResearchRun Execution Chunk succeeds, the executor retains only the
canonically serializable state needed to produce exactly the same next-session
calculation: bounded rolling-operator tails, unmatured 1-, 5-, and 20-session
Label inputs, ordered Factor aggregate state, Strategy account and scheduling
state, and incremental checksum state. The size of this live numeric state is
bounded by the frozen calculation contracts rather than by Research Period
length.

Completed Alpha cross-sections, matured stock-level Labels, and daily Factor
observations are folded into that state and released before the next chunk.
They are not accumulated in process memory or written as full historical
checkpoint datasets. Growing retained Strategy Daily Observations are streamed
to private immutable Staged Result Partitions, and the Checkpoint retains their
ordered checksum references instead of rebuilding one full-period payload in
memory.

Factor aggregation and checksum continuation must preserve original Research
Session order and the Numeric Execution Contract exactly. Combining approximate
per-chunk summaries, changing floating-point association, or recalculating old
chunks during finalization is not an accepted execution path. Chunked and
uninterrupted execution remain canonically identical under ADR-0102 and
ADR-0108.

The final Result remains ADR-0099's one atomic immutable Result Bundle. This
decision refines ADR-0146's transient-data rule: bounded private continuation
state may survive an infrastructure Attempt, but full historical Alpha, Label,
and daily Factor datasets remain neither retained Results nor checkpoint
artifacts.
