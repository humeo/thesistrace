---
status: accepted
---

# Rank V1 liquidity universes by 20-session average turnover amount

ThesisTrace V1 provides four nested Liquidity Universes containing the top 300,
1000, 2000, and 3000 instruments from the Universe Base Pool defined by
ADR-0075. After each market session closes, it ranks the pool by mean daily
turnover amount over the trailing 20 completed market sessions through that
close. The resulting score, unique one-based rank, and membership are stored as
a daily snapshot keyed by `as_of_date`. ADR-0076 defines the deterministic
tie-break and cutoff semantics.

The ranking pool contains ordinary A-shares whose recorded listing lifecycle is
active on `as_of_date` and that have sufficient history to compute the
liquidity measure. It never excludes a historical observation because the
instrument later delists. ST policy is a downstream research eligibility
decision; suspension and price-limit state are downstream execution
constraints. None of them silently changes the base Liquidity Universe.

The observation window is the 20 completed market sessions ending on
`as_of_date`, not the instrument's latest 20 non-missing records. A confirmed
full-session suspension contributes zero turnover amount; a partial suspension
with a valid bar contributes its observed amount. An unexplained missing
observation remains invalid and is not silently filled with zero. An instrument
with fewer than 20 post-listing sessions does not receive a rank. ADR-0074
defines these mutually exclusive trading states.
