---
status: accepted
---

# Claim ResearchRuns in strict FIFO order

All Research Workers claim from one PostgreSQL-backed ResearchRun Queue ordered
by original Run admission time and stable Run identity. An idle single-slot
Worker atomically selects the oldest eligible Run with row locking and
`SKIP LOCKED`, so concurrent Workers claim different Runs without a separate
scheduler service.

An infrastructure retry remains the same ResearchRun and retains that Run's
original queue order while resuming its validated Checkpoint. Retry eligibility
is still bounded by the accepted Attempt limit; a permanently failing older Run
cannot retry indefinitely.

Estimated Total Research Work informs progress and duration guidance but never
changes queue priority. ThesisTrace does not add shortest-job-first ordering,
long and short queues, user priorities, or queue-specific Worker classes. This
keeps scheduling deterministic and prevents long Research Periods from being
continually displaced by newer short Runs.

## Superseded clause

ADR-0208 supersedes only the statement that ThesisTrace does not add
queue-specific Worker classes. The strict-FIFO ResearchRun Queue and every
ordering rule in this decision remain accepted; only fixed-role Research
Workers may claim this queue.
