# 24 — Verify Batch-Incremental Equivalence

**What to build:** Prove that batch replay and session-by-session Daily Tracking
from the same Origin, semantics, target Release, Generation, and numeric/kernel
versions produce canonically exact results.

**Blocked by:** 15 — Calculate complete Strategy metrics; 20 — Mature Labels and publish Factor summaries; 23 — Replay a runtime-fix Generation.

**Status:** resolved

- [x] The batch oracle and incremental path call the same kernel with the same canonical input ordering and tie rules.
- [x] Alpha windows use complete ordered inputs and aggregates use retained ordered observations rather than a differently ordered online recurrence.
- [x] Verification compares missingness, reasons, Universes, ranks, orders, quantities, holdings, states, Labels, Factor results, costs, cash, NAV, and derived metrics.
- [x] Integer, Decimal, and binary64 comparisons use the canonical encodings rather than display text or numeric tolerance.
- [x] Historical session-by-session, catch-up, correction-Generation, and runtime-fix fixtures all verify exactly.
- [x] A mismatch fails verification with the first stable divergent coordinate and never advances a corrected Head.
- [x] Ordinary daily Advances remain incremental and do not run a full batch replay automatically.

## Comments

- Added an explicit fixed-Origin batch oracle and canonical exact comparator
  with binary64 byte encoding, exact integers/Decimals, and first-divergence
  coordinates.
- Acceptance covers one-session Advances, multi-session catch-up, correction
  replay, runtime-fix replay, blocked recovery, and duplicate delivery while
  ordinary strategy and Alpha updates stay incremental.
- Historical note: ADR-0144, ADR-0148, and the Bounded Research Storage Spec
  replace correction-Generation replay with an ordered Dataset Release
  sequence comparator. Alpha, Labels, orders, and fills may be compared during
  explicit verification without becoming durable result objects.
