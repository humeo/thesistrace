# 06 — Resume long Research across bounded Attempts

**What to build:** Preserve expensive committed Research work across transient Worker
and infrastructure failures without weakening correctness. A later Attempt validates
and resumes the same frozen Run from its latest private Checkpoint, while FIFO order,
bounded retry, fencing, permanent failure, and private-object cleanup remain explicit.

**Blocked by:** 05 — Admit and complete long Research through committed Chunks

**Status:** ready-for-agent

- [ ] Every Research Execution Checkpoint is immutable, fenced, checksummed, chained, and bound to immutable Run input, frozen Data Generation, compiler and calculation contracts, and the highest contiguous completed boundary.
- [ ] The Checkpoint references bounded continuation and ordered staged payload checksums rather than unbounded historical datasets.
- [ ] A later infrastructure Attempt selects the newest Checkpoint only after validating input, Generation, contracts, boundary chain, fence, and every referenced payload checksum.
- [ ] A valid retry resumes at the next uncompleted Chunk and produces the same canonical final Result as uninterrupted execution.
- [ ] Checkpoint or staged-payload mismatch is a terminal integrity failure and never causes restart-from-zero, best-effort merge, plan change, or alternate Generation selection.
- [ ] A ResearchRun has at most three total Attempts.
- [ ] Automatic retry is limited to unexpected Worker loss and transient PostgreSQL, RustFS, network, timeout, or Publication unavailability.
- [ ] Confirmed cgroup OOM, execution-memory breach, invalid Canonical Data, calculation or domain failure, contract mismatch, numeric failure, Result budget failure, and other permanent failures terminate on the first occurrence.
- [ ] Publication retry reuses validated continuation and Staged Result Partitions without recomputing completed Chunks.
- [ ] Research Workers claim the strict FIFO queue by original admission time and stable Run identity using atomic row locking; retries retain that original order.
- [ ] Estimated work, date range, and Run length do not change FIFO priority.
- [ ] A stale or recovered old Attempt cannot advance progress, commit another Checkpoint, publish another Result, or release the winning Attempt's Pin.
- [ ] Committed progress remains monotonic and resumes from the same boundary after Worker, container, API, PostgreSQL, or RustFS restart.
- [ ] Success, terminal failure, confirmed cancellation, and Research deletion end private checkpoint ownership and make unreferenced staged objects collectible.
- [ ] Public failure information distinguishes transient retry exhaustion, capacity, data, calculation, integrity, and generic permanent failure without exposing internals or secrets.
- [ ] Integration tests inject failure before a first Checkpoint, after multiple Checkpoints, during staging, during publication, and after a competing owner wins.
- [ ] Retry, stale-owner, garbage-collection, and restart tests use real PostgreSQL, RustFS, Worker and child processes with deterministic barriers and bounded polling.
- [ ] No resource-exhaustion retry, Chunk shrinking, compatibility reader, or hidden user-created replacement Run remains.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 05.
