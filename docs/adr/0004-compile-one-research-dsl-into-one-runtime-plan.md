---
status: superseded by ADR-0005
---

# Compile one Research DSL into one runtime plan

ThesisTrace V1 gives users and AI one Research DSL for describing the complete
hypothesis, data, universe, period, Alpha, evaluation rules, Strategy,
execution, and costs. The system parses and validates that source into one
canonical, immutable Compiled Research Plan with explicit defaults and
semantics; ResearchRun executes only this representation and produces separate
Factor Evaluation and Strategy Backtest conclusions. Raw DSL is never the
runtime contract, and V1 does not expose independently authored evaluation and
backtest plans whose inputs could drift apart. This decision supersedes
ADR-0003.
