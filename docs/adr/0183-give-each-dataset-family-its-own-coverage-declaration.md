---
status: accepted
---

# Give each Dataset Family its own Coverage declaration

Each Dataset Family Manifest in a Data Generation owns a Dataset Coverage
declaration matching that family's grain and information-time semantics. Market
Coverage remains a Research Session range; Financial Coverage records a complete
expected shard set, observation-through cutoff, historical reconciliation
watermark, and source revision-coverage limitations. The Generation root
aggregates these declarations without reducing them to their shortest common
date interval. Missing Financial Facts remain valid sparse data and visible
coverage loss, distinct from an incomplete Financial Refresh. A ResearchRun
never owns Coverage: execution only verifies that the families referenced by its
frozen Field References can supply the required calculation slice. A
ResearchRun using financial fields cannot extend beyond the family's
observation-through cutoff, and a DailyTrack using them blocks before the first
uncovered session until a complete Financial Refresh advances that cutoff;
market-only execution remains independent.
