---
status: accepted
---

# Separate ordinary Research, Batch Research, and Tracking Worker pools

The one Production Image and Worker executable expose three mutually exclusive
startup roles: `research`, `batch-research`, and `tracking`. A Worker freezes
its role at startup, has one execution slot, and never falls back to another
role. Ordinary Research Workers claim only non-Batch ResearchRuns, Batch
Research Workers claim only Research Batches, and Tracking Workers claim only
Tracking Advances; every pool scales independently by replica count.

These are three separate durable claim sets, not one shared queue with different
Worker consumers. A queued Batch-owned ResearchRun is never independently
claimable: its Batch Research Worker reaches it only through the claimed
Research Batch.

Batch Research Workers claim the oldest claimable Batch first, ordered by
admission time and then Batch ID, using the same durable lock-and-skip pattern as
the other Worker claim paths. There is no V1 priority or preemption. With
multiple Batch Worker replicas, FIFO governs claim and start order rather than
completion order: each replica claims the next distinct Batch and one shorter
later Batch may finish before an earlier longer Batch.

One Batch Research Worker claims one complete Research Batch. For a Factor
Evaluation Batch it prepares the common Data, Universe, and Labels once, then
executes each independent Alpha and Factor Evaluation in request order. For a
Strategy Sweep it prepares Data once, computes the one shared Alpha and Factor
once, then executes Strategy parameter combinations in request order. Additional
replicas process different Research Batches rather than splitting one Batch
across Workers. Durable Batch recovery advances only after one complete Alpha
and Factor unit or one complete Strategy succeeds; internal bounded Chunks
remain calculation details rather than Batch checkpoint boundaries.

One Research Batch Attempt owns exactly one execution child for its complete
lifetime. The child processes tasks sequentially and waits for a durable
supervisor acknowledgement after each complete Alpha or Strategy. Worker or
child loss ends that Attempt; a new Attempt and child resume from the first
incomplete task and never reuse an old execution process.

Retry accounting is durable across Batch Attempts and belongs to the current
complete task: one Alpha-and-Factor unit, the Strategy Sweep's shared
Alpha-and-Factor unit, or one Strategy parameter combination. A transient
infrastructure failure receives at most three total execution attempts;
deterministic input or calculation failures are permanent and are not retried.
An exhausted task fails according to its dependency scope, already completed
tasks are never recomputed, and execution continues with the next runnable task.

The child emits live progress heartbeats for the current task, including its
phase and completed Research Sessions when the phase is session-based. The
supervisor makes that information available as an Attempt-scoped estimate while
persisting completed-task acknowledgements as the recovery authority. Losing an
Attempt may reset only the incomplete task's live estimate; it does not change
the completed-task count.

A Strategy Sweep's completed shared Alpha and Factor may produce one private
immutable Batch-scoped artifact bound to the canonical Alpha, shared Research
scope, Data Generation, and calculation contracts. It is not a Result, is never
reused by another Research Batch, and becomes collectible after all dependent
Strategies are terminal. This narrow recovery and reuse boundary deliberately
does not create a permanent Alpha store.

The execution child writes only Attempt-scoped temporary files. The supervisor
validates their canonical binding, integrity checksum, and current fence before
atomically recording the private artifact in RustFS and acknowledging the
complete Alpha-and-Factor task. Temporary files without that durable record are
discarded and cannot be reused by a later Attempt.

After every dependent Strategy is terminal and no Batch Attempt is active, one
transaction releases the private artifact reference and enqueues any newly
unreferenced immutable objects through the existing durable Publication deletion
queue. Collection rechecks references under the Publication mutation lock before
deleting from RustFS. A deletion failure leaves the cleanup record available for
retry and never changes the Batch or ResearchRun outcome; aged unrecorded
Attempt files are handled as orphans only after the same authority recheck.

All three roles retain the same supervisor authority boundary: execution
children have no PostgreSQL or RustFS publication authority, while the
single-slot supervisor owns claims, leases, fences, Data Generation protection,
durable progress, and publication. The pool split isolates scheduling and
capacity without creating another Research Kernel or deployment artifact.

Cancelling a running Batch advances its fence before asking the child to stop.
The supervisor waits up to five seconds for cooperative exit, terminates the
child if it remains alive, and releases Data Generation protection only after
confirmed child exit and durable cancellation.

After that confirmation, cancellation retains no resumable state for the
incomplete task. Its Checkpoints, temporary output, and live heartbeat are
discarded, while already acknowledged task outcomes and already-published
ResearchRun Results remain authoritative. The ordinary private-artifact
reference release and durable deletion queue clean any shared artifact that no
longer has a nonterminal dependent Strategy.

Release qualification compares each Batch Kind against the equivalent ordered
ordinary ResearchRuns using the same Production Image and Data Generation. A
Strategy Sweep must prove one Data read, one Alpha calculation, one Factor
calculation, and one Strategy calculation per submitted item. A Factor Batch
must prove one common Data, Universe, and Label preparation plus one independent
Alpha-and-Factor calculation per submitted item. Result checksums must match
exactly, measured Batch elapsed time must be lower than the serial baseline, and
peak RSS must remain within the Worker execution budget. Crash recovery,
cancellation, failure isolation, temporary-object cleanup, and final Product
State are part of the same gate.
