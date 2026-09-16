# Allocate ordinary Research Execution Opportunities fairly by Researcher

Ordinary Research Workers select the Researcher with the fewest valid leased
allocations, then the oldest previous opportunity (first-time participants first),
then original admission time and stable identity. FIFO is scoped to each
Researcher; infrastructure retries retain their original order and bounded retry
policy. A lone Researcher may use all idle capacity. Existing work is not preempted,
and the policy promises neither equal CPU time nor a fixed maximum wait.

A short ordinary-pool PostgreSQL advisory lock precedes candidate observation.
Each claim atomically records new execution authority and a monotonic sequence in
durable per-pool Researcher history, which survives Run, Folder, and Chat deletion.
Rollback records no opportunity; a committed claim counts even if its Worker fails
before computation. Effective leases include cancellation pending confirmed exit;
expired executions cannot renew themselves. No runtime compatibility or schema
migration path is introduced: fresh environments initialize the current contract.

This replaces ADR-0202's global FIFO decision for ordinary research. Complete
Batches retain their existing claim policy until their separate fair-claim change
is delivered; Batch children consume no ordinary slots. Independent single-slot
Worker pools and complete Batch recovery boundaries remain unchanged.
