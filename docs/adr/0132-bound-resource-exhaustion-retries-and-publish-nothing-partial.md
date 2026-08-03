---
status: accepted
---

# Bound resource-exhaustion retries and publish nothing partial

A module-owned worker execution that exhausts its accepted resource envelope may
be attempted automatically at most one more time before the owning lifecycle
records `RESOURCE_EXHAUSTED` as failed or blocked. Bounded retry prevents restart
loops, and failed execution publishes no partial Result Bundle, Tracking
Checkpoint, or Dataset Release.
