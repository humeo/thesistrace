---
status: accepted
---

# Require thirty valid pairs for a daily Factor correlation

For one signal session and one Forward Return Label horizon, V1 calculates IC
and Rank IC only when at least 30 instruments have both a valid final Alpha
Value and a valid label. The Alpha cross-section and label cross-section must
also each have non-zero variation. For Rank IC, variation is assessed after the
standard average-rank conversion defined by ADR-0084.

If any condition fails, that session-horizon correlation is missing with a
sample-insufficient reason; it is not recorded as zero and does not enter the
two-year aggregate. Factor Evaluation reports both the valid instrument count
and its ratio to that session's Universe Membership.

V1 applies no additional percentage-based coverage gate. The fixed minimum
protects against correlations calculated from only a handful of instruments,
while the reported coverage ratio makes broader data loss visible. This rule
does not change Universe Membership or Strategy portfolio size.
