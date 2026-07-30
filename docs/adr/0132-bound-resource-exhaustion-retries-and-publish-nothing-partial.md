---
status: accepted
---

# Bound resource-exhaustion retries and publish nothing partial

If a Compute Activity is terminated by its container memory limit or otherwise
reports that it exceeded the accepted Worker resource envelope, Temporal may
execute it automatically at most one more time. The domain Attempt remains
nonterminal during that bounded automatic retry and records the failed Activity
execution for operator diagnosis.

If the second execution also exhausts its resource envelope, the domain Attempt
fails with `RESOURCE_EXHAUSTED`. A ResearchRun becomes terminally failed; a
Tracking Advance remains blocked and may receive a later explicitly requested
Attempt. The platform releases the Compute slot and nonterminal-job quota,
removes unreferenced staging objects and transient Alpha intermediates, and
never publishes a partial Result Bundle or Tracking Checkpoint. A User may
create a new ResearchRun only after changing the workload or after platform
capacity or implementation has changed.

Dataset Publication applies the same maximum of two Activity executions. If
both exhaust the Data Worker's resource envelope, the Publication Attempt
fails, its candidate objects remain unpublished and are cleaned up, the prior
Dataset latest pointer remains unchanged, and the failure is visible in
operator product state and dashboards.

`RESOURCE_EXHAUSTED` is an execution failure after admission. It is distinct
from `QUOTA_EXCEEDED`, disk-pressure admission rejection, Research Definition
validation, correctness-invariant failure, and an Alpha or Strategy producing
poor investment results. Temporal retry configuration must not turn resource
exhaustion into an unbounded restart loop.
