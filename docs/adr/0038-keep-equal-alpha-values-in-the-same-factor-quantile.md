---
status: accepted
---

# Keep equal Alpha Values in the same Factor quantile

When multiple instruments have the same final Alpha Value on one signal
session, V1 gives them their common average cross-sectional rank and assigns
all of them to the same Five-Quantile Return group. It never uses instrument
code or row order to split a tie merely to make group counts equal.

For an Effective Factor Sample of size `N`, ADR-0085 assigns the group as
`ceil(5 * average_rank / N)`. V1 performs no second balancing pass.

Consequently, Q1 through Q5 are approximately rather than exactly equal in
size. A large tie may leave a group empty. An empty group's return is missing,
and Top-Bottom Return is missing whenever either Q1 or Q5 is unavailable; the
runtime does not fill or reconstruct it.
