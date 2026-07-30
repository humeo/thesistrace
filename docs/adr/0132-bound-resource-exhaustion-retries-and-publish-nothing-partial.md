---
status: accepted
---

# Bound resource-exhaustion retries and publish nothing partial

An Activity that exhausts its accepted resource envelope may be executed automatically at most one more time before its Attempt fails with `RESOURCE_EXHAUSTED`. Bounded retry prevents restart loops, and failed execution publishes no partial Result Bundle, Tracking Checkpoint, or Dataset Release.
