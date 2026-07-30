---
status: accepted
---

# Break Strategy Alpha ties by instrument identity

At each scheduled Rebalance, V1 totally orders eligible target candidates by:

```text
final_alpha DESC
instrument_id ASC
```

It selects the first `holdings_count` instruments from that order. The
`instrument_id` key is used only when Final Alpha Values are exactly equal and
prevents database, storage, or source-response order from changing the Target
Portfolio.

After all eligible sells, ADR-0048 uses this same total order for buy-deficit
priority. If available cash cannot fund every selected target, the earlier
candidate receives its permitted buy before a later candidate.

This Strategy-specific cutoff does not change Factor Evaluation. ADR-0038
continues to assign equal Alpha Values one common average rank and keeps them
in the same factor quantile.
