---
status: accepted
---

# Keep operational telemetry diagnostic and Product State authoritative

PostgreSQL Product State remains the sole authority for ResearchRun,
ResearchRun Attempt, DailyTrack, Tracking Advance, Tracking Advance Attempt,
retry, lease, fence, Checkpoint, Result, and Data Refresh lifecycle.

Structured logs, health responses, and private diagnostic snapshots explain
that state but do not create, update, replay, reconstruct, or replace it.
Ownership and liveness are determined from PostgreSQL time and persisted lease
facts, never from recent telemetry. Retry, recovery, cancellation, Stop, and
publication likewise remain correct when every operational event has been lost
or rotated.

This keeps a temporary diagnostic layer from becoming a second state system and
allows collection and retention to change later without changing product
semantics. The trade-off is that short-lived container logs cannot provide a
permanent audit history; durable investigation must use the safe projections of
authoritative Product State.
