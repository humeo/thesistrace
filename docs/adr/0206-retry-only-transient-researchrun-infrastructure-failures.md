---
status: accepted
---

# Retry only transient ResearchRun infrastructure failures

A ResearchRun may make at most three total infrastructure Attempts. Automatic
retry is limited to an unexpected Worker loss and transient PostgreSQL, RustFS,
network, timeout, or publication unavailability. Each retry retains the Run's
FIFO position, frozen Data Generation and execution plan, and resumes only from
the latest fully validated ResearchRun Execution Checkpoint.

A supervisor-confirmed cgroup OOM or execution-memory breach is a deterministic
capacity failure on homogeneous 2c2g Workers and becomes terminal after its
first Attempt. Checkpoint checksum, boundary, input, compiler, numeric, or
calculation-contract mismatch; invalid Canonical Data; numeric or domain-rule
failure; Result budget failure; and every other permanent execution error are
also terminal on first occurrence. User cancellation follows ADR-0198 and never
creates another Attempt.

Checkpoint validation failure is an integrity error, not permission to restart
from the beginning. Likewise, a retry never shrinks the Chunk, selects another
Data Generation, changes calculation contracts, or discards a valid completed
boundary. A publication retry reuses validated continuation and staged result
state rather than recomputing completed Chunks.

Every failed Attempt publishes no partial Result, and bounded retry remains
under the same user-visible ResearchRun identity.
