---
status: accepted
---

# Require one post-execution holding interval for a Rebalance

A finite ResearchRun creates Rebalance orders only when both the next-session execution open and one later valuation open exist inside its Research Window, so terminal performance includes a post-execution holding interval. Terminal Valuation does not force liquidation, while an active DailyTrack waits for future opens instead of applying this moving terminal cutoff.
