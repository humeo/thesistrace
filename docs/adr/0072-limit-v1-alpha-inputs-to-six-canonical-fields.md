---
status: accepted
---

# Limit V1 Alpha inputs to six Canonical fields

V1 Alpha Expression permits exactly these Field References:

```text
open_adj
high_adj
low_adj
close_adj
volume_shares
turnover_amount_cny
```

The editor offers only the fields whose Data-owned Field Definitions carry an
Alpha Field Capability. Research Definition Run validation rejects every other
Field Reference even when the resolved Dataset Release contains that field,
and Run admission records the stable `field_id` binding for every permitted
reference in the immutable input.

Raw OHLC, `pre_close_reference_raw`, and `price_change_raw` remain in Field
Catalog for execution, validation, and provenance. They are not Alpha inputs
because company actions can introduce discontinuities into raw price history.
`source_adjustment_factor` and `adjustment_scale` are adjustment machinery, not
research features.

`pct_change_ratio` remains a source-normalized validation field rather than a
second Alpha return path. An author expresses a return through the closed
function set, for example:

```text
pct_change(close_adj, 1)
```

This keeps return calculations on the same Adjusted Research Price coordinate
and avoids using Tushare's rounded percentage field as an independent result.
The complete Field Catalog remains visible; Alpha authorability is a separate
capability of these six fields and is not configurable per ResearchRun.

Adding another Alpha input later requires Data to grant an explicit Alpha Field
Capability after its point-in-time, grain, type, unit, availability, missingness,
and Series-read contract pass review. Merely adding a Canonical field or Dataset
Schema version does not expose it to Alpha.
