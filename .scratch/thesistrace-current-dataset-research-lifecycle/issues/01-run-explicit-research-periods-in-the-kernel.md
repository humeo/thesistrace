# 01 — Run explicit Research Periods in the Kernel

**What to build:** Let the public Research Kernel run one explicitly bounded
Research Period of any positive length, using only the Alpha-derived
Calculation Warm-up and never turning the old synthetic 252-plus-504 shape into
a calculation rule.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Kernel Run accepts explicit first and last Research Sessions and derives Calculation Warm-up from the normalized Alpha Expression's Effective Alpha Lookback.
- [ ] One-session, two-session, and longer Research Periods run without a 20-, 504-, or 756-session minimum; an empty or reversed period is rejected explicitly.
- [ ] The existing 252-session Effective Alpha Lookback maximum remains enforced at expression validation, while smaller expressions request only their actual Warm-up.
- [ ] Warm-up sessions may precede the Research Period but create no reported Alpha signal, Forward Return Label sample, Factor observation, Strategy order, or Strategy Daily Observation.
- [ ] Forward Return Labels at horizons 1, 5, and 20 never read beyond the Research Period end; labels that cannot mature remain unavailable.
- [ ] Short Factor samples retain the existing nullable metrics and valid-session coverage counts rather than fabricating numeric zero or failing the Run.
- [ ] Strategy emits exactly one Daily Observation for each Research Period session and finishes with Terminal Valuation that retains cash and holdings without a final Rebalance or forced liquidation.
- [ ] If the supplied Canonical data cannot provide the complete derived Calculation Warm-up, Kernel Run returns an explicit insufficient-warm-up failure, preserves the Research Period, and never uses a partial rolling window; focused tests use minimal session sets rather than a standard 756-session fixture.
