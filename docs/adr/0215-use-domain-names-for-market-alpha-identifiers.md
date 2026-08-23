---
status: accepted
---

# Use domain names for Market Alpha Identifiers

The Alpha Formula authoring contract exposes concise market concepts while the
compiled Alpha Expression and Data Generation retain exact namespaced Field
References:

| Alpha Identifier | Canonical Field Reference |
|---|---|
| `open` | `price.open.adjusted` |
| `high` | `price.high.adjusted` |
| `low` | `price.low.adjusted` |
| `close` | `price.close.adjusted` |
| `volume` | `market.volume.shares` |
| `amount` | `market.turnover.cny` |

`adjusted`, `shares`, and `CNY` are Field semantics, not authoring choices. The
catalog exposes one price adjustment contract, one volume unit, and one turnover
unit, so suffixing every Formula reference makes authoring harder without
disambiguating anything. Financial identifiers retain projections such as
`latest_fy` and `latest_reported` because those suffixes select materially
different point-in-time meanings.

This is a Product State hard cut. `open_adj`, `high_adj`, `low_adj`, `close_adj`,
`volume_shares`, and `turnover_amount_cny` are no longer Alpha Identifiers and
must produce `UNKNOWN_IDENTIFIER`; there are no aliases, parser rewrites,
Draft migrations, or compatibility paths. Frozen ResearchRuns keep their
immutable Formula source and compiled Alpha Expression, while a newly submitted
Draft must use the current identifiers.

This decision replaces the authoring names listed by ADR-0072 and the examples
in ADR-0161. It preserves ADR-0191's separation between concise authoring names
and namespaced internal Field References.
