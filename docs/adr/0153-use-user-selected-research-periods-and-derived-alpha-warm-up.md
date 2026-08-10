---
status: accepted
---

# Use user-selected Research Periods and derived Alpha warm-up

Every ResearchRun requires a natural-date `start_date` and `end_date`. The
runtime maps that inclusive range to its first and last Research Sessions and
rejects a range containing no Research Session. The resulting Research Period
may contain any positive number of sessions; ThesisTrace no longer requires a
756-session input, a 252-session calculation-only prefix, or a 504-session
report.

The runtime derives Calculation Warm-up from the Alpha Expression's Effective
Alpha Lookback, which remains capped at 252 sessions by ADR-0029. Warm-up
supplies calculation inputs only and never contributes Alpha signals, Strategy
orders, Factor observations, or reported Strategy results. An Attempt whose
selected Data Generation cannot supply the derived history fails with an
explicit insufficient-warm-up reason rather than moving the requested period
or filling missing inputs.

Factor Evaluation and Strategy Backtest are bounded by the selected Research
Period. Forward Return Labels never read a session after `end_date`; labels
whose entry or exit lies beyond that boundary remain unavailable. A short but
otherwise valid period succeeds, with non-evaluable summary metrics represented
by the Result contract's existing `null` values and zero coverage counts rather
than a failed ResearchRun or a fabricated numeric zero. Strategy starts from
the all-cash baseline at the first Research Session, schedules orders only when
execution and one later valuation session remain inside the period, and ends
with a Terminal Valuation that retains rather than liquidates holdings.

The retained right-censoring classification is
`right_censored_by_research_period_end`; it replaces ADR-0086's obsolete
`right_censored_by_release_end` name without changing the classification's
meaning.

The durable Result contract remains exactly the current four top-level values:
`factor_summary`, `strategy_summary`, `strategy_daily_observations`, and
`terminal_strategy_state`. Its exact byte budget scales with the period as
`ceil(research_period_session_count / 504) * 1 MiB`: 1 through 504 sessions
receive 1 MiB, 505 through 1008 receive 2 MiB, and so on. Publication fails
rather than truncating a required result. Raw Alpha Values, stock-level Labels,
daily Factor observations, orders, fills, and position history remain transient.

Fixture and test data have no standard Research Period length. Each test uses
the smallest dataset needed for its behavior; the 252-session Alpha boundary is
tested at the expression or focused numeric layer rather than by routing a
756-session fixture through every product boundary.

This decision supersedes ADR-0068, ADR-0079, ADR-0080, and ADR-0147. It also
supersedes ADR-0029's fixed 252-session publication prefix while retaining that
ADR's maximum Effective Alpha Lookback and supersedes only the fixed-window
examples in ADR-0033. It also supersedes ADR-0086's Dataset-Release-end boundary
and fixed-504 examples while retaining its missing-label classifications.
In every other accepted ADR, a fixed `Research Window` or exact `Research Input
History` shape is superseded; the retained business rule applies to the
user-selected Research Period or its derived Calculation Warm-up as appropriate.
