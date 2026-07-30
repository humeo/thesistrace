# 18 — Activate a DailyTrack

**What to build:** Let the operator start and inspect one continuous DailyTrack
from a successful ResearchRun without modifying the seed Definition or Result
Bundle.

**Blocked by:** 16 — Run research and publish the Result Bundle; 17 — Harden ResearchRun lifecycle.

**Status:** resolved

- [x] Only a succeeded Run with a complete Result Bundle may seed a DailyTrack.
- [x] The Track pins seed Definition semantics, Numeric Execution Contract, fixed Tracking Origin, and the seed Run's exact Dataset Release.
- [x] Generation 0 inherits the seed calculation-kernel version and creates a predecessor-free Activation Checkpoint.
- [x] Activation references checksummed seed artifacts and carries terminal positions, units, cash, NAV, Benchmark, costs, labels, and rebalance phase without copying or mutation.
- [x] A scheduled final-session signal is retained if and only if its execution Research Session lies after the Activation Release.
- [x] Starting from an older successful Run queues catch-up from the seed Release rather than jumping to current latest.
- [x] Stopping is terminal in V1, prevents future work, and preserves Head and all published history.

## Comments

- Added idempotent activation from a complete successful Result Bundle,
  Generation 0, a predecessor-free reference-only Activation Checkpoint, fixed
  origin and terminal stop semantics.
- Older seeds enqueue their immediate real Release frontier; the Web result
  view can activate, inspect, reload, and stop the Track.
- Historical note: ADR-0148 and the Bounded Research Storage Spec supersede
  carrying persistent Alpha or Label history in Activation state. Activation
  creates a bounded, rebuildable Working Cache only for the new DailyTrack, and
  stopping the Track removes that non-authoritative cache.
