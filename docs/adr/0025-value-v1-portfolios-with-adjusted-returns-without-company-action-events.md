---
status: accepted
---

# Value V1 portfolios with adjusted returns without company-action events

V1 Strategy Backtest accrues each held instrument's return and portfolio value
from Adjusted Research Price, whose Source Adjustment Factor captures Tushare's
supported corporate-action adjustment semantics. It does not ingest or process
separate dividend, bonus-share, split, or other company-action events and does
not reconstruct a broker-style cash and share ledger.

ADR-0070 implements this as a dual-unit position: integer Execution Share
Quantity defines order constraints, while fractional Adjusted Holding Units
define Strategy valuation. Raw Market Price notional still defines fees, price
limits, and board-lot checks. A sale transfers proportional adjusted research
value rather than claiming to reproduce broker cash proceeds.

The resulting Strategy Backtest is a research total-return simulation, not a
broker account statement. ADR-0052 defines valuation during a confirmed
suspension.
