---
status: accepted
---

# Require thirty valid pairs for Five-Quantile analysis

For one signal session and Forward Return Label horizon, V1 calculates
Five-Quantile Returns and Top-Bottom Return only when the Effective Factor
Sample contains at least 30 valid Alpha-and-label pairs. A smaller sample makes
that session-horizon's complete Five-Quantile result missing; it is not
recorded as zero and does not enter aggregate quantile returns.

The threshold matches the fixed minimum used for IC and Rank IC in ADR-0036.
It adds no separate minimum per quantile. When the total sample is at least 30,
the average-rank assignment, unsplit ties, empty-group behavior, and missing
Top-Bottom behavior remain exactly as defined by ADR-0038 and ADR-0085.
