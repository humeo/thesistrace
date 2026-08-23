---
status: accepted
---

# Separate Research and Tracking Worker pools

The one Production Image and Worker executable expose two mutually exclusive
startup roles: `research` and `tracking`. A Worker freezes its role at process
startup and never falls back to the other role.

A Research Worker has one Research Execution Slot, claims only the strict-FIFO
ResearchRun Queue, owns at most one ResearchRun Attempt, and executes that
Run's Chunks sequentially. A Tracking Worker is also single-slot, claims only
Tracking Advance work, and owns at most one Tracking Advance Attempt. Each pool
is horizontally and independently scaled by changing its replica count.

Both roles use the same supervisor-and-child isolation pattern. A Tracking
Worker supervisor starts at most one execution child and exclusively owns the
Advance claim, lease, fence, Data Generation Pin, Working Cache, Tracking
Checkpoint, and publication. Its child reads only the frozen mounted Canonical
Data Generation and returns bounded calculation data; it has no PostgreSQL or
RustFS write authority. Tracking never switches execution mode according to
catch-up length.

For either role, one Attempt owns exactly one child for its complete lifetime.
The Research child processes Chunks sequentially and waits for the supervisor's
durable checkpoint acknowledgement before starting the next Chunk. The Tracking
child instead computes one all-or-nothing Advance Attempt from the authoritative
Tracking Head for its frozen, capacity-planned 1-to-64-session Target and
produces no cross-Attempt private checkpoint. Either child exits if its
supervisor connection is lost and is never reused across Attempts.
ResearchRun or DailyTrack remains the business lifecycle boundary above those
execution lifetimes.

Tracking Workers fairly rotate eligible DailyTracks. One Track receives at most
one Advance Attempt before other eligible Tracks, while a successful Track that
still lags returns to the tail for its next Advance. A transiently failed
Advance receives bounded retry delay and also returns to the tail instead of
holding one Tracking Execution Slot through its complete retry cycle. Separate
replicas may own different Tracks, but fencing prevents concurrent Advances for
one Track.

The role restriction applies to product execution work. When idle, either role
may claim at most one pending shared Publication deletion per poll under the
Publication mutation fence; it never drains the deletion backlog ahead of
claimable product work. Tracking Working Cache reconciliation belongs only to
the Tracking Worker. This keeps shared reclamation live when either pool is
scaled to zero without adding a Maintenance Worker role.

Both roles call the same Core data access, calculation, checkpoint, supervisor,
and publication modules. This is one engine and one deployment artifact, not a
V2 executor or two implementations. The split isolates scheduling and capacity;
it does not duplicate business rules.

Each pool has its own homogeneous deployment-declared CPU, hard-memory, and
thread capacity. Startup fails when a Worker's actual cgroup limits are below
its role declaration, and Research Chunk or Tracking Advance planning never
silently adapts already-frozen work to a smaller Worker.

ADR-0210 applies the same confirmed-child-exit invariant to Tracking Stop. A
Tracking supervisor never releases an Attempt Pin or exposes terminal `stopped`
while its child may still be running.
