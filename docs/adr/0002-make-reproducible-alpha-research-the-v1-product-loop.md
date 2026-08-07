---
status: superseded by ADR-0154
---

# Make reproducible Alpha research the V1 product loop

ThesisTrace V1 saves a Research Definition and embeds its immutable Run input
with one Dataset Release in a ResearchRun, evaluates one transient Alpha Matrix
through Factor Evaluation and Strategy Backtest, and publishes a reproducible
Result Bundle with provenance. A successful ResearchRun may seed a DailyTrack
whose incremental results are checked against the same ordered Dataset Release
sequence through explicit equivalence verification, keeping AI Chat,
notifications, and automated trading outside the V1 loop.
