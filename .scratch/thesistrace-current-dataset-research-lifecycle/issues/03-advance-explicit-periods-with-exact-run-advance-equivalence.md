# 03 — Advance explicit periods with exact Run/Advance equivalence

**What to build:** Advance the same calculation contract one or more Research
Sessions at a time and reach the exact retained state that one batch Kernel Run
would produce, without restoring a fixed input or report window.

**Blocked by:** 01 — Run explicit Research Periods in the Kernel.

**Status:** complete

- [x] Kernel Advance consumes explicit session boundaries, the same frozen calculation definition, and a bounded continuation state rather than inferring a 756-session origin.
- [x] Advancing one session at a time, several sessions at once, and all remaining sessions at once produces the same canonical retained state as one batch Run over identical Canonical Market Data.
- [x] Equivalence covers Final Alpha Cross-Sections, Factor summary continuation, Strategy cash and positions, pending signal and Rebalance phase, Daily Observations, and Terminal Strategy State.
- [x] Label maturation remains bounded by the finite batch Research Period while forward tracking can mature only evidence that becomes available in later supplied sessions.
- [x] Chunk boundaries do not duplicate signals, orders, Daily Observations, costs, or Factor samples.
- [x] The Numeric Execution Contract and canonical serialization remain identical between Run and Advance.
- [x] Tests cover short origins and irregular chunk sizes without requiring the maximum Alpha lookback or a 756-session fixture.

## Comments

- Implemented by `8c54f7a feat(kernel): advance explicit research periods`; threshold and compact-state review fixes are in `ecb82f1 fix(kernel): preserve full explicit advance state` and `b82c2a8 test(kernel): exercise compact explicit continuation`.
- Focused explicit/legacy Advance verification passed `25 passed in 175.03s`; the complete Kernel suite passed `92 passed in 100.98s`; the final compact 24/505-session proof passed `2 passed in 1.03s`.
- Review used fixed point `29662e0` for Standards and Spec. After threshold and real compact-state fixes, both dimensions ended with no remaining material findings. The fixed 504 selection remains only on the isolated legacy/rolling-continuation branch and is owned by Ticket 22 for final contraction.
