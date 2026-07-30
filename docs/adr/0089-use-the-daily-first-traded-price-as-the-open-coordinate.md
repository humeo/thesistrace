---
status: accepted
---

# Use the daily first-traded price as the Open coordinate

V1 defines an instrument's Open coordinate as the valid Canonical daily-bar
`open`: the session's first traded price for that instrument. It is not a
fixed 09:30 wall-clock coordinate and may occur after an opening suspension or
after a session begins without an immediate trade.

Every open-based subsystem uses that same coordinate:

- Strategy execution uses Raw Market Price `open`;
- Strategy NAV, Strategy Benchmark, and Forward Return Labels use the
  corresponding Adjusted Research Price `open`.

An `open_suspended_partial` session that later produces a valid daily bar
therefore remains open-eligible. Its first post-resumption trade is the daily
Open used for execution, valuation, Benchmark, and Labels. The full observed
bar also remains available after close for Alpha and liquidity. A later
`after_open_suspended` state likewise retains its valid daily Open.

Only `full_session_suspended` has no daily Open. It blocks both order sides,
permits Valuation Carry for an existing holding, contributes the defined zero
Benchmark return, and makes a required Forward Return Label coordinate
unavailable.

This remains a synthetic daily-bar full-fill model. V1 does not claim that an
order queued from 09:30 until resumption, and it does not simulate intraday
submission or waiting. It simply applies the frozen Strategy to the first
traded daily price when one exists.
