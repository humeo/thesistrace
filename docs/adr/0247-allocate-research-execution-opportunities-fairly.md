# Allocate Research Execution Opportunities fairly by Researcher

Ordinary Research and complete Batch Workers independently select the Researcher with the fewest valid leased
allocations, then the oldest previous opportunity (first-time participants first),
then original admission time and stable identity. FIFO is scoped to each
Researcher; infrastructure retries retain their original order and bounded retry
policy. A lone Researcher may use all idle capacity. Existing work is not preempted,
and the policy promises neither equal CPU time nor a fixed maximum wait.

A short per-pool PostgreSQL advisory lock precedes candidate observation; Batch
reuses its existing Publication → claim → Batch lock order.
Each claim atomically records new execution authority and a monotonic sequence in
durable per-pool Researcher history, which survives Run, Folder, and Chat deletion.
Rollback records no opportunity; a committed claim counts even if its Worker fails
before computation. Effective leases include cancellation pending confirmed exit;
expired executions cannot renew themselves. No runtime compatibility or schema
migration path is introduced: fresh environments initialize the current contract.

This replaces ADR-0202's global FIFO decision. A Batch's valid starting claim or
Attempt counts as one slot, including pending cancellation despite a changed fence;
its children consume no ordinary slots. An expired Batch whose old child has not
confirmed exit is skipped only for the current poll, without consuming an opportunity,
so other eligible work can proceed. Complete Batches remain indivisible; no child
task yielding, shared-computation change, or fine-grained recovery is introduced.
Independent single-slot Worker pools and complete Batch recovery boundaries remain unchanged.
