---
status: accepted
---

# Bound research throughput by memory

The old planner treated each Python bootstrap and execution deadline as expected
per-session work. Adding sequential programs could reduce an otherwise safe
Chunk to one session. Reopening overlapping history and compiling the same
standard library for every decision then dominated execution time.

Use memory to choose the largest safe Chunk up to the configured ceiling,
defaulting to 128 sessions. Keep the existing work estimates as diagnostics,
without using the historical 30-second target to reduce Chunk size. This policy
also applies to Tracking Targets through the shared capacity planner. Existing
admitted inputs stay frozen. Batch recovery still uses completed Alpha/Strategy
units; this change does not introduce finer durable recovery state.

Reuse verified market-column Arrow projections in a bounded 32 MiB LRU cache
per mounted Generation store. Immutable object hashes and projected fields are
the cache identity; each returned history applies its own permitted instruments
and date range. Oversized projections are read normally without retention. The
planner includes the cache allowance in Python decision memory.

Prepare standard-library bytecode once with the pinned WASI interpreter in its
private directory, before user source can execute. User calls retain fresh Stores,
read-only library access, capability revocation, deterministic inputs, and explicit
JSON state. No user globals or mutated standard-library modules survive calls.
The pinned interpreter, bootstrap source, authoring contract, and result semantics
are unchanged.

Research and Batch supervisors monitor child RSS independently of protocol
progress, terminating above the execution budget. Worker containers disable swap
by setting their combined memory-and-swap limit equal to their RAM limit. The
default 1.5 GiB child budget leaves room inside the 2 GiB container for supervision
and transport. Sampling is not a strict instantaneous RSS bound: cgroup enforcement
is the final resource boundary and confirmed OOM remains a permanent failure.
No fixed Chunk size guarantees arbitrary research will fit or complete.

Avoid persistent mutable Python guests, unbounded historical caches, and increased
timeouts as substitutes for removing repeated preparation. Tests cover exact data
visibility, cache eviction, guest isolation, and silent/partial-output child memory
failures. Performance evidence compares the same frozen research, container limits,
full-period result hash, and memory measurements before and after the change.
