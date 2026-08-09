# 02 — Reconcile transient Strategy Ledgers

**What to build:** Make every Strategy transition inspectable through a
transient per-session ledger so developers can prove accounting correctness
from hand-computed market data without turning orders, fills, or position
history into product storage.

**Blocked by:** 01 — Run explicit Research Periods in the Kernel.

**Status:** complete

- [x] The Kernel calculation output exposes, for every Research Period session, the signal, intended orders, fills or explicit rejection outcomes, cash, positions, transaction costs, Gross NAV, and Net NAV produced by the same Strategy transition used for the Result.
- [x] The transient Strategy Ledger is absent from durable Result Bundles, Tracking Checkpoints, and every product API response.
- [x] A hand-computed case proves that a signal from session T can only execute at T+1 Open and that the first session remains the all-cash baseline.
- [x] Focused cases prove that full-session suspension creates no fake fill, an upper-limit buy remains unfilled, and a lower-limit sell leaves the existing holding intact.
- [x] Focused cases prove Board-Lot Rounding, applicable board-specific lot rules, minimum commission, sell-side costs, and insufficient-cash sizing without negative cash.
- [x] Focused cases prove corporate-action value continuity, no future instrument before listing, explicit delisting behavior, and use of historical Universe Membership.
- [x] Every ledger row reconciles cash plus marked positions to NAV and reconciles transaction-cost changes to the executed fills for that session.
- [x] Repeating the same controlled input produces canonically identical ledger and retained Kernel output.

## Comments

- Implemented by `300ad63 feat(kernel): expose transient strategy ledger`; review fixes are in `a917701 test(kernel): close strategy ledger review gaps` and `b04485a test(kernel): pin strategy ledger slices`.
- Focused verification passed Ruff and `21 passed in 16.99s`; the complete Kernel suite passed `85 passed in 92.53s`; the final order/diagnostic slice check passed `14 passed in 11.96s`.
- Review used fixed point `354a2bd` for Standards and Spec. After two fix rounds, both dimensions ended with no remaining material findings. The ledger is structurally separate from retained artifacts and is available only through `RunOutput.strategy_ledger_snapshot()`.
