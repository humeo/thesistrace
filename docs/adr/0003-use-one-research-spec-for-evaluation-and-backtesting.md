---
status: superseded by ADR-0004
---

# Use one ResearchSpec for evaluation and backtesting

ThesisTrace V1 uses one complete ResearchSpec to define the hypothesis, data,
universe, period, Alpha, evaluation rules, Strategy, execution, and costs. A
ResearchRun freezes and consumes that complete definition, then produces
separate Factor Evaluation and Strategy Backtest conclusions; V1 does not
expose independently authored factor-evaluation and backtest jobs whose inputs
could drift apart.
