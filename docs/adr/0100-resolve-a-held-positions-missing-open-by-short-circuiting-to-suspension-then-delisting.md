---
status: accepted
---

# Resolve a held position's missing Open by short-circuiting to suspension then delisting

Strategy Backtest does not scan every instrument for terminal delisting on
every Research Session. It enters the exceptional-state path only for an
Actual Holding whose required daily Open is absent. Resolution short-circuits
in this fixed order:

1. a valid daily Open uses the normal execution and valuation path and performs
   no suspension or delisting lookup;
2. a missing Open first looks up the indexed Canonical Trading State;
3. confirmed `full_session_suspended` uses Valuation Carry and stops;
4. otherwise, explicit Tushare terminal-delisting evidence whose effective
   date has arrived produces a Terminal Delisting Write-Off; and
5. every other missing Open is an unexplained data-quality failure.

ResearchRun performs these lookups only against the immutable, locally indexed
evidence in its pinned Dataset Release. It never makes a per-position or
per-instrument Tushare request. Dataset Publication obtains and stores the
source evidence through the batch interfaces fixed by ADR-0097.

A Terminal Delisting Write-Off values the position at zero, removes it from
Actual Holdings, and produces no cash proceeds. It is an unscheduled accounting
event, not an execution: it creates no order, fill, Transaction Cost, Turnover,
or Market Rejection. Gross NAV and Net NAV both recognize the same complete
loss, and the daily Holdings Count falls accordingly.

V1 assigns no value to possible later over-the-counter trading, shareholder
claims, or compensation after terminal delisting. The zero is a conservative
synthetic research convention, not an observed market price.
