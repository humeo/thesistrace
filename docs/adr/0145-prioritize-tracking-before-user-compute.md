---
status: accepted
---

# Prioritize Tracking before User Compute

The first Hosted Platform V2 release uses two priority tiers on the shared
Temporal Compute Activity Task Queue:

- P1 contains every automatic Tracking Advance, including catch-up Advances,
  retries of the same persistent Advance, and ADR-0144 correction-boundary
  Advances.
- P3 contains user ResearchRuns and explicit equivalence verification.

The release assigns no normal Compute work to P2, P4, or P5. Dataset
Publication remains on its separate one-slot Data Worker Task Queue and does
not participate in Compute priority.

Temporal evaluates priority before fairness. All queued P1 work therefore
dispatches before queued P3 work; within one priority tier, Personal Workspace
identity remains the equal-weight fairness key, and tasks with the same
priority and Workspace dispatch FIFO. Priority affects only the next available
Worker slot. It never interrupts, cancels, or restarts an Activity that is
already running.

The first self-hosted Compute Activity Task Queue uses one partition. Temporal
priority is enforced within a partition, while its default multi-partition
layout can dispatch lower-priority work from one partition ahead of
higher-priority work waiting in another. One partition is appropriate for the
accepted four-slot, low-throughput first node and preserves the intended
platform-level P1-before-P3 ordering. Increasing Task Queue partitions later
requires new ordering and capacity evidence.

P1 prevents a User's admitted ResearchRun backlog from delaying Daily Tracking
freshness. The high-priority burst is bounded by at most 10 active
DailyTracks per Personal Workspace and by Dataset Publication cadence. P3 work
still receives work-conserving capacity whenever no P1 Activity is waiting.

Historical data corrections create no replay task: ADR-0144 handles them as P1
Tracking Advances in the existing Generation. A result-changing calculation
kernel correction under ADR-0109 is an exceptional maintenance operation, not
a normal admitted P1 or P3 workload; ordinary admissions remain paused while
the operator handles that boundary.
