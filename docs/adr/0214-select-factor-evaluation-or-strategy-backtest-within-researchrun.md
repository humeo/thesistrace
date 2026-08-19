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

Both kinds reuse the same admission, Data Generation Pin, FIFO Worker, Chunk,
Checkpoint, retry, cancellation, recovery, and Publication lifecycle; there is
no separate Factor resource, Worker role, or calculation engine. Only Strategy
Backtest accepts Strategy parameters and may seed a DailyTrack. Factor
Evaluation publishes only `factor_summary`; Strategy Backtest additionally
publishes its Strategy summary, daily observations, and terminal state, without
empty placeholders. Identical frozen Factor inputs and Data Generation must
produce an identical `factor_summary` in both kinds. Moving from Factor
Evaluation to Strategy Backtest uses the existing Use as Draft action rather
than a new derived-Run action.
