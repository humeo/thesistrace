---
status: accepted
---

# Use a conservative full-fill open execution model

V1 first attempts each Strategy order at the next market session's Raw Market
Price open. The daily open is the instrument's first traded price and is not
fixed to 09:30. A confirmed `full_session_suspended` state blocks both sides
because no daily open exists. A buy cannot execute when the valid open equals
the session's published upper price limit; a sell cannot execute when it equals
the published lower price limit. The opposite sides remain eligible.

An `open_suspended_partial` session with a valid later daily bar executes at its
first post-resumption traded open; a suspension beginning after the valid daily
open also does not block it. ADR-0089 defines this common Open coordinate. A
missing or invalid open without governing full-session suspension evidence is
the data-integrity failure defined by ADR-0074, not an ineligible order.

The next-open price is a synthetic Backtest fill assumption, not a claim that
the exchange offers a native market-at-open order. V1 uses the published daily
open only as its deterministic End-of-Day Research execution coordinate.

Canonical Market Data obtains the session-specific upper and lower limit prices
from Tushare. The execution model does not infer a universal percentage such
as 10 percent across instruments and sessions.

Every otherwise eligible order fills completely at the Raw Market Price open.
V1 does not simulate order-book queues, partial fills, volume participation,
market impact, or slippage. ADR-0045 defines behavior when an order is
ineligible at that open. ADR-0050 defines Transaction Costs.
