---
status: accepted
---

# Scale Research concurrency with single-slot Workers

Each Research Worker replica has exactly one Research Execution Slot and owns at
most one active ResearchRun Attempt. Its supervisor starts at most one execution
child process inside that slot. After claiming a Run, the child executes all of
its ResearchRun Execution Chunks sequentially, and the Worker cannot claim
another Run until the Attempt ends or loses ownership. The Run is never split
across multiple Workers during one Attempt.

Attempt is the execution-child lifecycle boundary, Chunk is the checkpoint
boundary, and ResearchRun is the user-visible business lifecycle boundary. One
child stays alive for one Attempt, waits for a durable supervisor acknowledgement
after every Chunk, and exits at Attempt end; it is never pooled or reused across
Attempts.

The supervisor exclusively owns Product State authority for the Attempt,
including its lease, fence, Data Generation Pin, Checkpoints, and publication.
The execution child has no PostgreSQL or RustFS write authority and returns only
bounded per-Chunk data for supervisor validation and commit.

The slot provides one explicit CPU and memory envelope. The Run's Estimated Peak
Execution Footprint must fit that one envelope, and Arrow or NumPy parallelism
is bounded by the threads assigned to the Worker process. ThesisTrace does not
coordinate several concurrent Runs through one process-level memory pool.

Every Research Worker replica in a pool uses the same deployment-declared CPU,
hard-memory, and thread capacity. Startup fails when actual cgroup limits are
below that declaration, and a capacity change never silently replans an
already-admitted Run.

System ResearchRun concurrency is the number of horizontally replicated
Research Workers. PostgreSQL claim locking and execution fencing ensure that
separate Workers own different Runs, while a Worker-loss retry may resume the
same Run's validated Checkpoint on another single-slot Worker.

This keeps the module-first PostgreSQL-claimed Worker topology from ADR-0151
and rejects in-process multi-Run execution, cross-Worker time-Chunk execution,
and a second distributed scheduler. Increasing concurrency is an operational
replica-count change rather than another execution-engine path. The supervised
child is an isolation and cancellation boundary, not another execution slot or
concurrent Run.
