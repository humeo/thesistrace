# 11 — Calculate complete Factor Evaluation

**What to build:** Turn Effective Factor Samples into immutable daily and
aggregate Factor Evaluation artifacts for all three fixed horizons.

**Blocked by:** 10 — Build Forward Labels and Effective Factor Samples.

**Status:** ready-for-agent

- [ ] Daily Pearson IC and standard average-rank Spearman Rank IC require at least 30 valid pairs and non-constant arrays.
- [ ] Missing correlations retain sample-insufficient reasons and never enter aggregates as zero.
- [ ] IC and Rank IC retain complete daily series and report mean, sample deviation, unannualized ICIR, positive fraction, and valid-session count.
- [ ] Five quantiles use average Alpha rank and never split exact ties by identity or row order.
- [ ] Quantile and Top-Bottom results require 30 pairs, preserve empty groups, and remain Factor diagnostics without Strategy costs.
- [ ] All three horizons consume the identical Alpha observations and produce separately checksummed result objects.
- [ ] Public calculation-seam golden tests cover ties, constants, small samples, missing labels, and deterministic ordering.
