---
status: accepted
---

# Bound resource-exhaustion retries and publish nothing partial

A module-owned worker execution that exhausts its accepted resource envelope may
be attempted automatically at most one more time before the owning lifecycle
records `RESOURCE_EXHAUSTED` as failed or blocked. Bounded retry prevents restart
loops, and failed execution publishes no partial Result Bundle or Tracking
Checkpoint and never moves the Dataset Head to a partial candidate.

ADR-0206 supersedes the automatic resource-exhaustion retry above for
ResearchRun: a capacity breach is deterministic and immediately terminal. The
partial-publication rule remains accepted. ADR-0209 independently applies the
same no-retry rule to Tracking Advance capacity failures and permits at most
one initial plus two automatic Attempts in a Tracking Attempt Cycle, only for
transient infrastructure failure. The original one-additional-Attempt resource
policy remains accepted only for other module-owned lifecycles until separately
changed.
