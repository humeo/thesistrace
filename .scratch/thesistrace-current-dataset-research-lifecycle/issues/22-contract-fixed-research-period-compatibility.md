# 22 — Contract fixed Research Period compatibility

**What to build:** Remove the legacy fixed-window calculation forms after Run,
Advance, Result, and Track consumers have migrated to explicit Research Period
and continuation contracts, without deleting unrelated legitimate 252 or 504
domain constants.

**Blocked by:** 03 — Advance explicit periods with exact Run/Advance equivalence; 15 — Retry and Rerun against the then-current Head; 18 — Recover DailyTrack without duplicate or partial history; 19 — Keep DailyTrack forward-only across overlap corrections.

**Status:** ready-for-agent

- [ ] Active Kernel, ResearchRun, Result, and DailyTrack call paths contain no exact-756 input admission, implicit 252-plus-504 execution, tail-selected Research Period, or exact-504 Result requirement.
- [ ] Run and Advance accept only explicit Research Period, derived Warm-up, and explicit continuation semantics; no caller silently substitutes the last sessions of its input.
- [ ] Result publication no longer accepts a legacy fixed-504 projection and scales only from the actual Research Period session count.
- [ ] One-, two-, 504-, 505-, and longer-session behavior remains green after legacy adapters are removed, without a standard 756-session fixture in broad gates.
- [ ] Architecture guards target fixed ResearchRun-window semantics and deliberately allow the Alpha lookback maximum 252, trading-year constants, DailyTrack's latest-504 Factor window, and unrelated HTTP status values.
- [ ] Contracting compatibility changes no Warm-up, Label, Factor, Strategy, retry, Rerun, or forward-only Track result already proven by predecessor tickets.
- [ ] Existing tests are migrated with their owning behavior rather than replaced by one monolithic fixed-fixture cleanup gate.
