# 03 — Advance explicit periods with exact Run/Advance equivalence

**What to build:** Advance the same calculation contract one or more Research
Sessions at a time and reach the exact retained state that one batch Kernel Run
would produce, without restoring a fixed input or report window.

**Blocked by:** 01 — Run explicit Research Periods in the Kernel.

**Status:** ready-for-agent

- [ ] Kernel Advance consumes explicit session boundaries, the same frozen calculation definition, and a bounded continuation state rather than inferring a 756-session origin.
- [ ] Advancing one session at a time, several sessions at once, and all remaining sessions at once produces the same canonical retained state as one batch Run over identical Canonical Market Data.
- [ ] Equivalence covers Final Alpha Cross-Sections, Factor summary continuation, Strategy cash and positions, pending signal and Rebalance phase, Daily Observations, and Terminal Strategy State.
- [ ] Label maturation remains bounded by the finite batch Research Period while forward tracking can mature only evidence that becomes available in later supplied sessions.
- [ ] Chunk boundaries do not duplicate signals, orders, Daily Observations, costs, or Factor samples.
- [ ] The Numeric Execution Contract and canonical serialization remain identical between Run and Advance.
- [ ] Tests cover short origins and irregular chunk sizes without requiring the maximum Alpha lookback or a 756-session fixture.
