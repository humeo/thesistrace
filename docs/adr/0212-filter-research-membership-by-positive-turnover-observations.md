---
status: accepted
---

# Filter Research membership by positive-turnover observations

Canonical Liquidity Universe Membership remains the complete point-in-time
Top-N liquidity ranking. Research derives one Effective Universe for each
signal session before any Alpha, Factor, Strategy new-buy, or Strategy
Benchmark calculation. A ranked member enters that Effective Universe only
when the same session has one complete Canonical EOD Price observation with
valid Raw and Adjusted Opens and strictly positive CNY turnover amount.

Zero turnover, an absent EOD Price observation, or an incomplete price
coordinate has one calculation consequence: the ranked member is absent from
that session's Effective Universe. The calculation does not branch on whether
the underlying diagnostic reason is suspension, upstream unavailability, or
another governed state. Data collection and Publication retain those reasons
and continue to enforce their own source-integrity rules independently.

The filter is applied once at the Market Research Series boundary, and both the
row and columnar calculation paths expose only the resulting Effective Universe
through their shared `universe_members` contract. Alpha cross-sections, Factor
inputs, Strategy new-buy candidates, and the selected-universe equal-weight
Benchmark therefore cannot diverge in eligibility. The Benchmark denominator
uses the signal session's Effective Universe; it does not look ahead to the
entry or exit session.

This rule does not rewrite Canonical Liquidity Rank or Universe Membership and
does not discard an existing Actual Holding. Existing positions continue under
the ordinary valuation, execution, scheduled-rebalance, suspension, and
terminal-delisting rules. A member can re-enter the Effective Universe on a
later signal session after a complete positive-turnover observation appears.

This rule is part of the single active calculation identity under ADR-0211;
Product State accepted under different semantics is reset without erasing the
mounted Canonical Data Store or Dataset Head.

This decision refines ADR-0022, ADR-0039, ADR-0046, ADR-0053, and ADR-0074 by
placing signal-session calculation eligibility before their downstream
Benchmark and Strategy rules. Their point-in-time, valuation-carry, execution,
and source-integrity requirements remain accepted.
