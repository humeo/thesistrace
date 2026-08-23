---
status: accepted
---

# Make one immutable Result Bundle the ResearchRun truth

Each successful ResearchRun atomically publishes one immutable Result Bundle
whose Result Manifest binds its immutable input, Data Generation provenance,
calculation contracts, payload identities, and checksums. A Factor Evaluation
bundle contains its bounded Factor result; a Strategy Backtest bundle adds the
Strategy summary, Strategy Daily Observations, and Terminal Strategy State
required for tracking. Alpha Values, stock-level Labels, daily Factor
observations, and raw execution details remain transient, and a failed Attempt
publishes no partial bundle.
