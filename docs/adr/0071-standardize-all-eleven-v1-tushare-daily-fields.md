---
status: accepted
---

# Standardize all eleven V1 Tushare daily fields

Dataset Publication always requests and retains the eleven long-history fields
in the Tushare `daily` contract. A Research Definition does not select source
fields.

The accepted source response preserves the original field names, values, and
source units. Publication then maps each source field into the
`equity.eod_price` Dataset Family:

| Tushare field | Canonical field | Canonical type and unit |
| --- | --- | --- |
| `ts_code` | resolve `instrument_id`; retain `ts_code` in Instrument Identity | string |
| `trade_date` | `session_date` | date |
| `open` | `open_raw` | decimal CNY per share |
| `high` | `high_raw` | decimal CNY per share |
| `low` | `low_raw` | decimal CNY per share |
| `close` | `close_raw` | decimal CNY per share |
| `pre_close` | `pre_close_reference_raw` | decimal CNY per share |
| `change` | `price_change_raw` | decimal CNY per share |
| `pct_chg` | `pct_change_ratio` | decimal ratio, source value divided by `100` |
| `vol` | `volume_shares` | integer shares, source value multiplied by `100` |
| `amount` | `turnover_amount_cny` | decimal CNY, source value multiplied by `1000` |

`pre_close_reference_raw` preserves Tushare's ex-rights reference-close
semantics. It must not be interpreted as an alias for the preceding row's
`close_raw`. `price_change_raw` preserves the Tushare `change` value against
that reference close; Publication must not replace it with
`close_raw[t] - close_raw[t-1]`.

The exact decimal value `vol * 100` must be an integer before Publication maps
it to `volume_shares`. A non-integral result is invalid source data; Publication
does not round or truncate it.

Dataset Publication separately requests Tushare `adj_factor`. Because it has a
different source-availability timeline from the post-close daily bar, it belongs
to the dated `equity.adjustment_factor` Dataset Family:

| Canonical field | Canonical type and unit | Constraint |
| --- | --- | --- |
| `instrument_id` | string | valid Instrument Identity |
| `session_date` | date | source `trade_date` |
| `source_adjustment_factor` | decimal, dimensionless | finite and greater than zero |

Publication derives the following `equity.eod_price` fields under ADR-0023:

| Canonical field | Canonical type and unit | Constraint |
| --- | --- | --- |
| `adjustment_scale` | decimal, dimensionless | finite and greater than zero |
| `open_adj` | decimal dynamically front-adjusted CNY per share | valid raw field and scale |
| `high_adj` | decimal dynamically front-adjusted CNY per share | valid raw field and scale |
| `low_adj` | decimal dynamically front-adjusted CNY per share | valid raw field and scale |
| `close_adj` | decimal dynamically front-adjusted CNY per share | valid raw field and scale |

ADR-0023 selects each instrument's latest available factor in the Data
Generation as the denominator. Publication therefore recomputes retained
adjusted OHLC when a later factor becomes the reference.

A present raw daily bar without a valid same-session
`source_adjustment_factor` fails Dataset Publication; V1 does not forward-fill
the factor. A factor row may exist for a confirmed suspended session that has
no daily bar, but Publication does not invent an `equity.eod_price` row or
Adjusted Research Price for that session. ADR-0074 restricts this governed
absence to `full_session_suspended`; every unknown daily-bar loss fails
Publication.

Canonical decimal values are not stored as binary floating-point source facts.
A research engine may use a documented numeric execution type internally, but
that does not change the Dataset Schema type or unit.

Publication owns one explicit, versioned source-field request list. New
upstream fields do not silently enter Canonical Market Data: adding one requires
a new Dataset Schema version under ADR-0014. Users therefore never configure
Tushare `fields`, while Dataset Releases still record exactly which source
contract and Canonical schema they contain.

Field Catalog exposes the complete Canonical inventory, including definitions,
units, coverage, and Dataset Release availability. Catalog presence does not by
itself make a field available to Alpha Expression; ADR-0072 fixes the V1
Alpha-authorable subset.
