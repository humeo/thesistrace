---
status: accepted
---

# Start an explicit DailyTrack from a successful ResearchRun

A DailyTrack starts only through an explicit action on a successful Strategy
Backtest ResearchRun and fixes that Run, its immutable input, successful Result
provenance, Terminal Strategy State, and calculation contracts as its Tracking
Origin. Factor Evaluation cannot seed a Track, Data Refresh never creates one,
activation is subject to the Active DailyTrack Limit, and a stopped Track is
terminal rather than resumable.
