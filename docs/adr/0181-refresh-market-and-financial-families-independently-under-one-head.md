---
status: accepted
---

# Refresh market and financial families independently under one Head

ThesisTrace exposes separate Market Refresh and Financial Refresh operator
actions while retaining one Dataset Head and one Attempt-pinned Data Generation.
Each action materializes only its target family group, reuses unchanged family
Manifest digests, and publishes one fully validated Generation root. Publication
uses the expected Head as an atomic compare-and-swap boundary: when another
refresh has already moved the Head, the stale root is not published; the target
family candidate must be combined with the new unchanged-family manifests and
cross-family invariants revalidated. Financial collection therefore does not
delay or fail a Market Refresh, without introducing independently mutable market
and financial Heads at execution time.
