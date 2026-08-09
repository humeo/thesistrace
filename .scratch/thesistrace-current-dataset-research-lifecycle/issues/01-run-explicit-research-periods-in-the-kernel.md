# 01 — Run explicit Research Periods in the Kernel

**What to build:** Let the public Research Kernel run one explicitly bounded
Research Period of any positive length, using only the Alpha-derived
Calculation Warm-up and never turning the old synthetic 252-plus-504 shape into
a calculation rule.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] Kernel Run accepts explicit first and last Research Sessions and derives Calculation Warm-up from the normalized Alpha Expression's Effective Alpha Lookback.
- [x] One-session, two-session, and longer Research Periods run without a 20-, 504-, or 756-session minimum; an empty or reversed period is rejected explicitly.
- [x] The existing 252-session Effective Alpha Lookback maximum remains enforced at expression validation, while smaller expressions request only their actual Warm-up.
- [x] Warm-up sessions may precede the Research Period but create no reported Alpha signal, Forward Return Label sample, Factor observation, Strategy order, or Strategy Daily Observation.
- [x] Forward Return Labels at horizons 1, 5, and 20 never read beyond the Research Period end; labels that cannot mature remain unavailable.
- [x] Short Factor samples retain the existing nullable metrics and valid-session coverage counts rather than fabricating numeric zero or failing the Run.
- [x] Strategy emits exactly one Daily Observation for each Research Period session and finishes with Terminal Valuation that retains cash and holdings without a final Rebalance or forced liquidation.
- [x] If the supplied Canonical data cannot provide the complete derived Calculation Warm-up, Kernel Run returns an explicit insufficient-warm-up failure, preserves the Research Period, and never uses a partial rolling window; focused tests use minimal session sets rather than a standard 756-session fixture.

## Comments

- Implemented by `a9d8a6f feat(kernel): run explicit research periods`; review fixes are in `a85775e test(kernel): verify one-session continuation state`.
- Focused verification passed Ruff and the complete Kernel suite: `82 passed in 141.11s`. The review fix rerun passed `17 passed in 5.50s` for explicit-period and Strategy behavior.
- Review used fixed point `84d67e5` for two rounds. Standards and Spec ended with no unresolved material findings; Run/Advance equivalence remains owned by Ticket 03 and final fixed-window compatibility removal by Ticket 22.
