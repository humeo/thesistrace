---
status: accepted
---

# Select Factor Evaluation or Strategy Backtest within ResearchRun

One ResearchRun freezes a Research Kind chosen on the existing Research
authoring surface: `factor_evaluation` ends after the shared Alpha and Factor
pipeline, while `strategy_backtest` continues through the existing Strategy
pipeline. The Research form exposes one two-choice Research Type control and
new Browser Drafts default to Factor Evaluation; Holdings Count and Rebalance
Sessions appear only for Strategy Backtest. Research lists and details display
the frozen Type, and each detail renders only the sections valid for that Type.

Within each admission path, both kinds reuse the same Data Generation,
calculation, retry, cancellation, recovery, and Publication semantics; there is
no Factor-specific resource, Worker role, or calculation engine. An ordinarily
admitted Run uses the strict-FIFO Research Worker path. A Research Batch-owned
Run is excluded from that queue and receives the equivalent Result through the
dedicated Batch Research lifecycle in ADR-0218. Only Strategy Backtest accepts
Strategy parameters and may seed a DailyTrack. Factor Evaluation publishes only
`factor_summary`; Strategy Backtest additionally publishes its Strategy summary,
daily observations, and terminal state, without empty placeholders. Identical
frozen Factor inputs and Data Generation must produce an identical
`factor_summary` in both kinds. Moving from Factor Evaluation to Strategy
Backtest uses Create draft followed by ordinary Run, rather than a derived-Run
action.
