---
status: accepted
---

# Bound ResearchRun chunks by memory, time, and 64 sessions

At Run admission, the deterministic planner selects the largest fixed Chunk
session count from 1 through 64 that both fits the 1.5 GiB execution-memory
budget and is estimated to execute within 30 seconds on the 2c2g development
Research Worker Capacity. The estimate uses the compiled Formula work, required
fields and live plan nodes, calculation contracts, and the maximum complete
single-session Universe cardinality across the selected calculation range.

The 30-second value is a Chunk-sizing target, not an admission limit. If one
complete Research Session fits the peak-memory budget but is estimated to exceed
30 seconds, admission selects a fixed Chunk size of one and records that the
time target is exceeded. Only inability to fit one complete session in memory
rejects the Run.

The planner partitions the ordered Calculation Warm-up followed by the Research
Period at that fixed count. Warm-up-only Chunks are valid and commit bounded
continuation state while ResearchRun Progress remains at zero completed Research
Period sessions. The final Chunk may be shorter. Every boundary and its capacity
facts are frozen with the admitted execution plan and remain identical across
infrastructure Attempts.

If one complete Research Session cannot fit the peak-memory limit, admission
rejects the Run explicitly. ThesisTrace does not split that session by
instrument, change Chunk size after observing runtime, or retry with a smaller
Chunk. When the single-session time estimate already exceeds 30 seconds,
ADR-0198's supervised execution child still enforces confirmed cancellation.
Otherwise, the 30-second target leaves time for checkpoint persistence and
runtime variance under ADR-0204's 45-second first-Checkpoint gate, while the
64-session hard maximum bounds lost work and progress silence when estimates
are imperfect.

This refines ADR-0196's contiguous full-Universe session chunks without changing
their order, exact-equivalence requirement, or single-engine execution path. The
64-session execution maximum and the Canonical Data Store's 64-session physical
partition contract deliberately share one count but remain independent
contracts; changing a checkpoint boundary never rewrites or redefines immutable
storage partitions.
