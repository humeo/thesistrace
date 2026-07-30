---
status: accepted
---

# Align Factor labels and Strategy execution on next-open-to-open timing

An Alpha Value for market session `t` is produced after that session closes
using only Canonical Market Data and Universe Membership available through
`t`. Strategy orders based on that value are first attempted at the Raw Market
Price open of session `t+1`.

For each V1 Factor Evaluation horizon `h`, Factor Evaluation pairs `Alpha[t]`
with the following Adjusted Research Price return:

```text
open_adj[t+1+h] / open_adj[t+1] - 1
```

ADR-0033 fixes `h` to 1, 5, and 20 market sessions for every V1 Factor
Evaluation. Strategy execution and holding-return accounting use the same
successive-open time convention, but Strategy rebalance frequency is a separate
decision. A valid entry Open is always required; without it the Alpha Value has
no label for that horizon and order execution is unavailable. After a valid
entry, ADR-0101 assigns a `-100%` Label when explicit terminal delisting makes
the required exit Open unavailable. Every other unavailable entry or exit
follows ADR-0086's release-end censoring, confirmed open unavailability, or
unexplained-data rules. ADR-0044 defines the remaining open-execution
eligibility rules.
