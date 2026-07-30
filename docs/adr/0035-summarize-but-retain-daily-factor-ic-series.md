---
status: accepted
---

# Summarize but retain daily Factor IC series

For each of the 1-, 5-, and 20-session Forward Return Label horizons, V1 retains
the valid daily IC and Rank IC observations as ResearchRun result data and
shows their time series. The main Factor Evaluation summary reports, separately
for IC and Rank IC:

- arithmetic mean;
- sample standard deviation;
- ICIR, defined as the mean divided by the sample standard deviation without
  annualization;
- fraction of valid observations greater than zero; and
- number of valid market sessions.

An ICIR with a zero or unavailable denominator is missing rather than infinite.
V1 does not report an ordinary t-test or p-value because the overlapping 5- and
20-session Forward Return Labels make an independence assumption misleading.
One ResearchRun produces one report; retaining daily observations does not
produce a separate report for each session.

ADR-0099 stores these observations in the ResearchRun's immutable structured
Result Bundle. The report is a derived view and not a second result store.

ADR-0106 appends newly mature Label and daily Factor observations in Tracking
Checkpoints without editing that Result Bundle. Each Checkpoint publishes a
new Factor Summary Snapshot over its latest 504 signal sessions.
