# 24 — Verify Batch-Incremental Equivalence

**What to build:** Prove that batch replay and session-by-session Daily Tracking
from the same Origin, semantics, target Release, Generation, and numeric/kernel
versions produce canonically exact results.

**Blocked by:** 15 — Calculate complete Strategy metrics; 20 — Mature Labels and publish Factor summaries; 23 — Replay a runtime-fix Generation.

**Status:** ready-for-agent

- [ ] The batch oracle and incremental path call the same kernel with the same canonical input ordering and tie rules.
- [ ] Alpha windows use complete ordered inputs and aggregates use retained ordered observations rather than a differently ordered online recurrence.
- [ ] Verification compares missingness, reasons, Universes, ranks, orders, quantities, holdings, states, Labels, Factor results, costs, cash, NAV, and derived metrics.
- [ ] Integer, Decimal, and binary64 comparisons use the canonical encodings rather than display text or numeric tolerance.
- [ ] Historical session-by-session, catch-up, correction-Generation, and runtime-fix fixtures all verify exactly.
- [ ] A mismatch fails verification with the first stable divergent coordinate and never advances a corrected Head.
- [ ] Ordinary daily Advances remain incremental and do not run a full batch replay automatically.
