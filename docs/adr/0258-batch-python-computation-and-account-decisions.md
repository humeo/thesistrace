---
status: accepted
---

# Batch Python computation and account decisions

Replace the daily-only class SDK with one current function contract:
`compute(data, state)` returns a bounded block of `Targets`, or `Values` when
`decide(data, account, state)` is present. Event-only programs may define just
`decide`. This changes the Python environment to `python-strategy/v5`.

The numerical entrypoint runs ordinary Python/NumPy over up to 128 output
sessions plus at most 252 preceding observations. Strategy rules, including
lookback, selection, ranking and rebalance cadence, remain source code. The
runtime neither classifies programs by Alpha nor translates code to formulas.
The same calculation Adapter serves Direct and Framework modules.

The shared simulator remains the account authority. It advances Open fills,
costs, cash and Close observations in order. Targets consume one output column
without a daily guest call. Optional per-stock/date priority preserves author
buy order in the shared simulator: descending priority, then canonical ID; absent
priority uses canonical ID. This matters when available cash cannot fill all
weights, so weights alone are not equivalent to a ranked formula selection.
Only selected priority values cross the guest boundary, with bounded indices
validated against the target mask; their numerical precision is preserved.
Values feed only their current column to the
optional account decision. Framework stage rules remain composition semantics,
not separate numerical execution engines. DailyTrack appends T=1 through this
same path and retains origin-relative session ordinals.

## Ownership and lifetime

The generic prepared Python Module owns private execution sessions, loading,
fuel, deadlines, deterministic clock/entropy capabilities and bounded I/O.
It knows nothing about trading stages. A private session installs trusted
modules and author source once, reuses its Store, and exports explicit state
at the owner's checkpoint. Failed sessions close and cannot be reused.
The Strategy Adapter owns observation scope, batch coordinates, output
validation, compute/decision separation and state/checkpoint policy.

Calculation and decision heaps are separate. Decisions receive copied current
columns, without a future ndarray base or compute globals. Financial history
uses the existing generation resolver per observation date. Common market
inputs reuse formula aggregation and historical universe/industry membership.
No current or batch-end membership is backfilled into earlier dates.

State supports bounded JSON containers and numeric arrays encoded with standard
NPY, without pickle. The host validates shape, dtype and size before constructing
arrays. Compute state represents the completed block, never an early decision.
The current terminal envelope stores compute and decision memory separately;
the simulator and publication transaction retain their existing atomic account,
pending-target, checkpoint and event guarantees. Failed uncommitted work may be
recomputed. Globals and live Python stacks are not durable state.

A numerical compute call currently has an isolated heap. Account decisions reuse
one heap across the calculation slice. At the next checkpoint slice or recovery,
explicit state is restored into a newly loaded private session. Keeping an author
heap alive for an entire multi-chunk Run is not required for correctness.

## Causality is a changed promise

Raw multi-date arrays cannot preserve the old physical guarantee that every
Python calculation can read only the current day's observations. A program can
use the last input column to contaminate an earlier result. Read-only arrays,
separate decision heaps and output coordinates do not prevent that mistake.
This explicitly supersedes the corresponding daily-only visibility/lifetime
claims in ADR-0250, ADR-0252 and ADR-0257; isolation from host authority remains.

Authors must produce causal, partition-invariant outputs and explicit state.
Each multi-date block is checked against first-date and midpoint prefixes in
independent heaps with the same incoming state. Detected differences fail before
any block account progress is accepted; verification calls publish no state.
Prefix truncation, future-data perturbation, alternative partitions and recovery
checks can find violations, but finite checks are not proofs for arbitrary
Python. Configuration diagnosis checks source loading and entrypoint signatures,
not every dynamic branch. A constrained causal expression graph could offer a
stronger guarantee, but is not the free-Python interface adopted here.

ADR-0108's canonical exact batch/incremental equivalence remains the product
invariant for an accepted program. Date-addressed RNG sources, stable ID order,
continuous ordinals and exact equal-allocation helpers support it. Equivalent
formula and arbitrary NumPy source are not automatically bit-identical when
floating reduction order, NaN rules or tie handling differ.

## Resources, rollout and verification

Keep the task's existing 2 GiB hard limit and supervisor protection. A 128-day
cap does not bound arbitrary intermediate arrays. Dynamic reads reserve cell
budgets before materialization; response, output, state and guest memory have
independent bounds. Increase bounded array transport to a 32 MiB cumulative
read response and 16 MiB output, while preserving 128 MiB guest memory and
current execution deadlines. No unbounded history cache or automatic package
installation is introduced.

Freeze the new bootstrap, SDK, numerical codec, limits and execution policies
in environment identity. Historical inputs/results stay unchanged. Old frozen
environments and class programs fail explicitly; there is no runtime ABI
fallback or silent database rewrite. Drain pending work and explicitly resolve
old active DailyTracks before activating the same revision in API and Workers.
Starting a new Track from an obsolete Python environment is rejected before
creating a Track; the historical Result remains readable and can seed a new draft.

Verify through real WASI calls and the shared simulator, partition/restoration
and actual-account behavior, bounded failure/isolation, generation-backed PIT
reads, research/track persistence and installed-image execution. Measure frozen
real-data cases serially under the same task resources, separating calculation,
transfer, ledger and publication costs. A lower callback count alone is not a
performance result. Follow [AGENTS.md](../../AGENTS.md#testing) for commands and
verification selection. User-facing details and complete examples live in the
[writing guide](../python-strategy.md) and shared Web/HTTP/MCP SDK reference.
