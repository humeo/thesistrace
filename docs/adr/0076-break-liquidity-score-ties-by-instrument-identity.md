---
status: accepted
---

# Break liquidity-score ties by instrument identity

For each `as_of_date`, V1 sorts the complete rankable Universe Base Pool by:

```text
mean_turnover_amount_cny DESC
instrument_id ASC
```

The first key is the trailing-20-session arithmetic mean defined by ADR-0010.
The second key is applied only when those Canonical mean values are exactly
equal. It gives every instrument one unique, one-based Liquidity Rank; V1 does
not assign shared or skipped ranks.

The Top 300, 1000, 2000, and 3000 cutoffs are applied after this total ordering.
They therefore remain deterministically nested and contain exactly their
requested number of instruments whenever the rankable pool is large enough.
Neither storage order nor source-response order may decide a cutoff tie.

V1 persists this ordering once per `as_of_date`, not as four Top-N membership
copies. The daily `equity.liquidity_rank` Canonical Session Partition contains
at most the first 3000 rows with `trade_date`, `instrument_id`,
`mean_turnover_amount_cny_20d`, and `liquidity_rank`. Top 300, 1000, 2000, and
3000 memberships are filtered views using `liquidity_rank <= N`. The Universe
Base Pool remains a separate logical snapshot, and ranks below 3000 are not
persisted in V1.
