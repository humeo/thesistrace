---
status: accepted
---

# Exclude point-in-time ST stocks from V1 Research Eligibility

V1 always excludes an instrument carrying an ST or `*ST` designation on signal
session `t` before that session's Final Alpha Cross-Section and from the
Strategy's new-buy candidate set. It uses only the historical designation
effective on `t`; it never applies the instrument's current status
retrospectively. The excluded output cannot enter an industry-neutralization
mean.

The exclusion does not alter Liquidity Universe ranking or Universe Membership.
Factor Evaluation reports the excluded instrument count as a distinct coverage
reason. Browser Draft does not expose an ST-inclusion option.

An existing position is not sold immediately when its instrument becomes ST.
ADR-0046 defines its behavior at the next scheduled Rebalance.
