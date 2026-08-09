# 02 — Reconcile transient Strategy Ledgers

**What to build:** Make every Strategy transition inspectable through a
transient per-session ledger so developers can prove accounting correctness
from hand-computed market data without turning orders, fills, or position
history into product storage.

**Blocked by:** 01 — Run explicit Research Periods in the Kernel.

**Status:** ready-for-agent

- [ ] The Kernel calculation output exposes, for every Research Period session, the signal, intended orders, fills or explicit rejection outcomes, cash, positions, transaction costs, Gross NAV, and Net NAV produced by the same Strategy transition used for the Result.
- [ ] The transient Strategy Ledger is absent from durable Result Bundles, Tracking Checkpoints, and every product API response.
- [ ] A hand-computed case proves that a signal from session T can only execute at T+1 Open and that the first session remains the all-cash baseline.
- [ ] Focused cases prove that full-session suspension creates no fake fill, an upper-limit buy remains unfilled, and a lower-limit sell leaves the existing holding intact.
- [ ] Focused cases prove Board-Lot Rounding, applicable board-specific lot rules, minimum commission, sell-side costs, and insufficient-cash sizing without negative cash.
- [ ] Focused cases prove corporate-action value continuity, no future instrument before listing, explicit delisting behavior, and use of historical Universe Membership.
- [ ] Every ledger row reconciles cash plus marked positions to NAV and reconciles transaction-cost changes to the executed fills for that session.
- [ ] Repeating the same controlled input produces canonically identical ledger and retained Kernel output.
