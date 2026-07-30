# 18 — Activate a DailyTrack

**What to build:** Let the operator start and inspect one continuous DailyTrack
from a successful ResearchRun without modifying the seed Definition or Result
Bundle.

**Blocked by:** 16 — Run research and publish the Result Bundle; 17 — Harden ResearchRun lifecycle.

**Status:** ready-for-agent

- [ ] Only a succeeded Run with a complete Result Bundle may seed a DailyTrack.
- [ ] The Track pins seed Definition semantics, Numeric Execution Contract, fixed Tracking Origin, and the seed Run's exact Dataset Release.
- [ ] Generation 0 inherits the seed calculation-kernel version and creates a predecessor-free Activation Checkpoint.
- [ ] Activation references checksummed seed artifacts and carries terminal positions, units, cash, NAV, Benchmark, costs, labels, and rebalance phase without copying or mutation.
- [ ] A scheduled final-session signal is retained if and only if its execution Research Session lies after the Activation Release.
- [ ] Starting from an older successful Run queues catch-up from the seed Release rather than jumping to current latest.
- [ ] Stopping is terminal in V1, prevents future work, and preserves Head and all published history.
