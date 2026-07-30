---
status: accepted
---

# Reassess existing-position eligibility only at scheduled Rebalances

At each scheduled Strategy signal session, an existing position receives a zero
target if its instrument:

- is absent from that session's Universe Membership;
- has no valid final Alpha Value;
- carries an ST or `*ST` designation; or
- ranks outside the selected Top-N target set.

The runtime first attempts the resulting sell at the next session's open under
the Open Execution Model. A successful sell removes the position. A Blocked
Order leaves it unchanged until a later scheduled Rebalance recalculates the
target and, when still required, creates another sell.

V1 does not trigger an unscheduled or intraday liquidation when one of these
conditions arises between Rebalances.

The Terminal Delisting Write-Off in ADR-0100 is not an eligibility liquidation
or a trade. It is the separate accounting treatment for an Actual Holding that
has no daily Open after explicit terminal-delisting evidence becomes effective.
