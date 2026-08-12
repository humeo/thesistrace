---
status: accepted
---

# Make one immutable Result Bundle the ResearchRun truth

Each successful ResearchRun atomically publishes one immutable Result Bundle
whose Result Manifest binds its immutable input, Attempt Data Generation
provenance, calculation
contracts, payload identities, and checksums. The bundle retains only the
bounded Factor and Strategy summaries, Strategy Daily Observations, aggregates,
and Terminal Strategy State required by the current Result contract; Alpha Values, stock-level
Labels, daily Factor observations, and raw execution details remain transient.
