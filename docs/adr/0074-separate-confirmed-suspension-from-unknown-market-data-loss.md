---
status: accepted
---

# Separate confirmed suspension from unknown market-data loss

The Data module maps Tushare daily bars and dated suspension evidence into
one `equity.trading_state` observation per active instrument and Research
Session. The Canonical state is exactly one of:

```text
normal
open_suspended_partial
after_open_suspended
full_session_suspended
```

`open_suspended_partial` means a confirmed suspension covers the wall-clock
session opening but trading later produces a valid daily bar.
`after_open_suspended` means a valid daily open occurs before the confirmed
suspension starts. `full_session_suspended` is a confirmed governed absence of
the daily bar. Publication retains the source suspension interval and fails
when source evidence cannot determine one unique state.

Strategy execution treats only `full_session_suspended` as a `suspension`
Market Rejection. Both partial states retain a valid daily Open: the first
traded price after an opening suspension or the price observed before a later
suspension. ADR-0089 uses that Open consistently for execution, valuation,
Benchmark, and Labels.

A full-session suspension has these fixed consequences:

- no Canonical EOD Price row or Alpha input is invented;
- a held position may use Valuation Carry;
- a Strategy Benchmark member remains in the denominator with zero return; and
- its Liquidity Observation Window contribution is zero turnover amount.

ADR-0212 qualifies the Benchmark consequence above: a member suspended on the
signal session is excluded from that session's Effective Universe, while a
member eligible on the signal session and suspended only on a later entry or
exit session retains the zero-return carry. Canonical trading-state and
Liquidity Observation Window semantics are unchanged.

A partial suspension with a valid daily bar keeps that observed bar and its
actual turnover amount for research and valuation. The bar is not replaced by a
zero or a Valuation Carry. Its first traded daily `open` is also the valid
Open coordinate under ADR-0089.

For an active instrument, a missing or invalid daily bar or `open` without
confirmed governing suspension evidence is an unknown market-data loss. It is
neither a Market Rejection nor an Execution Diagnostic. Data Generation validation
fails before moving the Dataset Head; a ResearchRun that nevertheless
detects it fails rather than treating it as suspension, zero turnover, or a
blocked order.

A contradiction such as a valid daily bar paired with
`full_session_suspended`, or suspension evidence whose interval cannot be
interpreted relative to the execution open, also fails Publication. A later
Tushare correction enters a validated candidate Data Generation. The Head moves
only after the complete candidate passes validation.

ADR-0100 separately handles an Actual Holding that remains after its instrument
has left the active Base Pool through explicit terminal delisting. That
short-circuit path checks confirmed suspension before terminal-delisting
evidence and never reclassifies an active instrument's unexplained data loss as
delisting.
