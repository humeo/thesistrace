---
status: accepted
---

# Make ResearchRun cancellation cooperative and confirmed

Cancelling a queued ResearchRun moves it directly to terminal `cancelled`
because no execution owns resources. Cancelling a running ResearchRun instead
moves the Run and active Attempt to non-terminal `cancelling`, advances the
execution fence immediately, and signals the execution owner. The fence
prevents every later Checkpoint or Result commit from that Attempt.

Each Research Worker supervises at most one execution child process inside its
single Research Execution Slot. The child checks cancellation at least before
and after each Research Session and between bounded expensive operator stages.
It abandons the current uncommitted Chunk, acknowledges that calculation has
stopped, and exits before the Worker releases the Data Generation Pin and makes
the Run and Attempt terminal `cancelled`. Previously committed private
Checkpoints remain inaccessible and become collectible with terminal
cancellation.

The supervisor, not the child, owns the Attempt lease, execution fence, Data
Generation Pin, checkpoint commit, and Result publication. The child cannot
commit Product State or RustFS publication bytes, so terminating it cannot race
a late durable publication after the supervisor has fenced cancellation.

An Attempt ending for success, failure, cancellation, ownership loss, or lost
supervisor connection always ends its execution child. A child never survives
for reuse by another Attempt.

Confirmed cancellation has one five-second total budget. If cooperative
shutdown exceeds the shorter internal grace interval, the Worker supervisor
terminates the execution child and reserves the remainder of that budget to
confirm process exit, release the Pin, and record terminal `cancelled`.
ThesisTrace never reports terminal cancellation or releases protected input
while the old child may still be reading or calculating.

That five-second budget applies while the owning supervisor remains alive. If
the supervisor, container, or host is lost, the durable cancellation intent and
fence remain, the child exits on supervisor-connection loss, and recovery waits
until the old lease and ownership can no longer be live. This recovery path may
exceed five seconds rather than releasing protected input without proof.

This supersedes ADR-0095's direct `running -> cancelled` transition for
ResearchRun while retaining queued cancellation, fencing, terminal cancellation,
and the rule that later user execution creates a new ResearchRun. The UI exposes
`cancelling` as real non-terminal progress rather than optimistically displaying
`cancelled` while work continues.
