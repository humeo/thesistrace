---
status: accepted
---

# Bound each ResearchRun to a minimal one-MiB Result Bundle

Each successful ResearchRun publishes a minimal immutable Result Bundle containing bounded Factor and Strategy summaries, retained Strategy Daily Observations and aggregates, and Terminal Strategy State, while the Alpha Matrix, stock-level Forward Return Labels, daily Factor observations and curves, target histories, and raw execution details remain transient. The exact bytes of every ResearchRun-owned manifest and payload must total no more than `1,048,576` bytes, and publication fails rather than dropping a required result or hiding excluded intermediates elsewhere.
