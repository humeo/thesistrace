---
status: accepted
---

# Use daily cross-sectional Rank IC as the primary Factor metric

For every market session and each fixed Forward Return Label horizon, V1 Factor
Evaluation forms the cross-section of instruments having both a valid final
Alpha Value and a valid label. It calculates:

- Rank IC: the Spearman correlation between Alpha Values and Forward Return
  Labels, as the primary metric. ADR-0084 fixes standard average-rank tie
  semantics and constant-input behavior.
- IC: the Pearson correlation between Alpha Values and Forward Return Labels,
  as a secondary metric.

The two-year evaluation aggregates the resulting daily IC series. It never
pools all instrument-session observations into one correlation, because that
would mix cross-sectional prediction with market and time effects. ADR-0035
defines the aggregate summary statistics, and ADR-0036 defines daily sample
validity.
