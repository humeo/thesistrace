# 03 — Execute one Research Chunk in a supervised child

**What to build:** Execute an existing short Research end to end as one bounded
full-Universe Research Chunk inside a supervised read-only child. The supervisor owns
all durable authority, the new PyArrow and NumPy path produces the canonically exact
Result, and the obsolete in-process whole-period Python-object execution path is
removed.

**Blocked by:** 02 — Run fixed-role single-slot Worker pools

**Status:** ready-for-agent

- [ ] One Research Worker claim creates one ResearchRun Attempt and exactly one execution child for that Attempt.
- [ ] The supervisor exclusively owns the lease, execution fence, frozen Data Generation Pin, Product State writes, Publication staging, and final commit.
- [ ] The child has read-only access to the frozen mounted Data Generation and no PostgreSQL or RustFS publication authority.
- [ ] The short Run is represented by one contiguous Chunk containing the complete eligible Universe for every included Research Session.
- [ ] PyArrow performs selective Parquet scanning, projection, filtering, null-mask handling, and bounded RecordBatch interchange.
- [ ] NumPy is used only for vectorized numeric kernels not supplied by Arrow, and calculation threads stay within Worker Capacity.
- [ ] Rows are deterministically ordered by Research Session and instrument before order-sensitive Alpha, Factor, or Strategy calculation.
- [ ] The Research path does not expand a whole selected period through `to_pylist`, full-period Python dictionaries, or defensive deep-copy graphs.
- [ ] The child returns bounded calculation data; the supervisor validates the current fence before staging and atomically publishing one immutable Result.
- [ ] The child waits for the supervisor's terminal acknowledgement, exits at Attempt end, and is never reused by another Attempt.
- [ ] Loss of the supervisor connection causes the child to exit without continuing calculation or publishing anything.
- [ ] Market-only, financial-only, and composite short Formulae produce canonical bytes identical to the accepted reference execution contract.
- [ ] A stale child cannot publish after another owner advances the fence.
- [ ] Integration tests use an actual child process, PostgreSQL, and RustFS and prove that the child cannot mutate owned durable state.
- [ ] The old direct whole-Run kernel call from the Worker path and any second execution route are deleted in the same change.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 02.
