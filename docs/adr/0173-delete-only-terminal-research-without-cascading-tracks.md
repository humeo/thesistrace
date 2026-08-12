---
status: accepted
---

# Delete only terminal Research without cascading Tracks

Users may permanently delete a ResearchRun only after it reaches one of the
terminal states `succeeded`, `failed`, or `cancelled`. A `queued` or `running`
Research must first complete or be cancelled and reach a terminal state; Delete
does not double as Cancel. Deletion removes the Research resource, its Attempts,
receipts, results, and owned artifacts only when those objects have no remaining
durable reference. It never deletes or mutates a DailyTrack seeded from that
Research. The Track retains its copied Tracking Origin and seed `run_id` as
provenance, continues independently, and is removed only by a separate explicit
user DailyTrack deletion action.
