---
status: accepted
---

# Resume infrastructure retries from private ResearchRun checkpoints

A non-terminal ResearchRun may own private immutable execution checkpoints that
survive an individual Worker and ResearchRun Attempt. Each checkpoint is
fenced, identifies the highest contiguous completed execution boundary, binds
the immutable Run input and frozen Data Generation, and checksums its bounded
continuation state and staged result payloads.

A retrying infrastructure Attempt resumes from the latest checkpoint only
after verifying the Run input, Data Generation, compiler and calculation
contracts, completed-boundary chain, and every referenced payload checksum.
Any mismatch is an explicit integrity failure rather than a silent restart or
best-effort merge. A stale Attempt cannot advance the checkpoint. A user action
that creates another ResearchRun, including Run after Create draft, never
inherits it.

The Research Worker supervisor exclusively owns the Attempt claim, lease,
execution fence, Data Generation Pin, private staged publication, and checkpoint
commit. Its one execution child has read-only access to the frozen Canonical Data
Generation, computes one bounded Chunk at a time, and returns bounded
continuation and result data to the supervisor. The supervisor validates that
data and its still-current fence before committing anything durable; a killed or
stale child has no PostgreSQL or RustFS publication authority.

One Attempt is the lifecycle boundary of exactly one execution child. That child
stays alive only for the Attempt and processes its Chunks sequentially. After
returning one Chunk result, it waits while the supervisor validates, stages, and
commits the matching Checkpoint; only an explicit commit acknowledgement permits
the next Chunk. Loss of the supervisor connection makes the child exit without
continuing or committing anything, and no child is reused by another Attempt.

Execution checkpoints are not Results and expose no partial research output.
The successful Attempt still atomically publishes exactly one immutable Result
Bundle under ADR-0099. Success, terminal failure, cancellation, or Research
Deletion ends checkpoint ownership and makes its private objects collectible;
therefore cancellation cannot later resume hidden work.

Private checkpoints refine infrastructure retry without creating another
user-visible ResearchRun, execution-engine version, or partial Result
publication boundary.
