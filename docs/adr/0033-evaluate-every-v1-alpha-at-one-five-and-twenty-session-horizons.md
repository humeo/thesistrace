---
status: accepted
---

# Evaluate every V1 Alpha at one, five, and twenty-session horizons

Every V1 Factor Evaluation assesses the same Alpha Values against fixed
Forward Return Labels of 1, 5, and 20 market sessions:

```text
1-session:  open_adj[t+2]  / open_adj[t+1] - 1
5-session:  open_adj[t+6]  / open_adj[t+1] - 1
20-session: open_adj[t+21] / open_adj[t+1] - 1
```

Each metric observation is attributed to the Alpha's signal session `t`, not
to the label's exit session. It becomes calculable only after its required exit
open exists: `t+2`, `t+6`, or `t+21`, respectively. Recent signal sessions
without that future open inside the selected Research Period remain unlabeled.
ADR-0086 defines the corresponding availability reasons.

The three horizons are sections of one Factor Evaluation produced by one
ResearchRun. They do not create additional Alphas, runs, orders, or portfolios,
and V1 does not expose arbitrary Factor Evaluation horizons. Each horizon joins
its labels independently to the same Final Alpha Cross-Section. A missing label
changes only that horizon's Effective Factor Sample and never causes Alpha
recalculation.

Strategy rebalance frequency and holding behavior remain separate Strategy
decisions. They are not inferred from these Factor Evaluation horizons.
