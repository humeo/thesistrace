---
status: accepted
---

# Resolve missing Benchmark and Label Opens on demand for terminal delisting

Factor Evaluation and Strategy Benchmark do not scan every instrument for
terminal delisting on every Research Session. A valid required daily Open uses
the ordinary path without a status lookup. Only a missing required Open
triggers a lookup against the locally indexed suspension and
terminal-delisting evidence in the pinned Dataset Release; neither subsystem
calls Tushare during ResearchRun.

For a Strategy Benchmark member with a valid starting Adjusted Research Price:

- confirmed `full_session_suspended` at the ending coordinate retains the
  existing zero-return carry in ADR-0053;
- explicit effective terminal delisting at the ending coordinate supplies a
  synthetic terminal value of zero and therefore a `-100%` member return; and
- every other unexplained missing ending Open is a data-quality failure.

For a Forward Return Label, the `t+1` entry Open must be valid because a return
cannot be formed without a starting value. Confirmed full-session suspension or
terminal delisting before that entry makes the Label unavailable with
`confirmed_market_open_unavailable`.

After a valid entry Open exists, explicit terminal delisting on or before the
required `t+1+h` exit coordinate supplies a synthetic terminal value of zero,
so the Label is exactly `-100%`. Full-session suspension at the exit remains an
unavailable Label under ADR-0086, while every unexplained missing exit remains
a hard data-quality failure.

The synthetic zero is not a daily Open or Canonical Market Data observation. It
is the same conservative terminal-loss convention as ADR-0100, extended only
to required Benchmark and Label return endpoints so terminally delisted
instruments are not silently removed from reported performance.
