---
status: accepted
---

# Break liquidity-score ties by instrument identity

For each `as_of_date`, the Data module assigns one unique Liquidity Rank by sorting the rankable Universe Base Pool on trailing-20-session mean turnover amount descending and then `instrument_id` ascending. Persisting one deterministic ranking and deriving each Liquidity Universe by cutoff keeps memberships nested and prevents storage or Tushare response order from deciding ties.
