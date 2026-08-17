# 03 — Execute one Research Chunk in a supervised child

**What to build:** Execute an existing short Research end to end as one bounded
full-Universe Research Chunk inside a supervised read-only child. The supervisor owns
all durable authority, the new PyArrow and NumPy path produces the canonically exact
Result, and the obsolete in-process whole-period Python-object execution path is
removed.

**Blocked by:** 02 — Run fixed-role single-slot Worker pools

**Status:** complete

- [x] One Research Worker claim creates one ResearchRun Attempt and exactly one execution child for that Attempt.
- [x] The supervisor exclusively owns the lease, execution fence, frozen Data Generation Pin, Product State writes, Publication staging, and final commit.
- [x] The child has read-only access to the frozen mounted Data Generation and no PostgreSQL or RustFS publication authority.
- [x] The short Run is represented by one contiguous Chunk containing the complete eligible Universe for every included Research Session.
- [x] PyArrow performs selective Parquet scanning, projection, filtering, null-mask handling, and bounded RecordBatch interchange.
- [x] NumPy is used only for vectorized numeric kernels not supplied by Arrow, and calculation threads stay within Worker Capacity.
- [x] Rows are deterministically ordered by Research Session and instrument before order-sensitive Alpha, Factor, or Strategy calculation.
- [x] The Research path does not expand a whole selected period through `to_pylist`, full-period Python dictionaries, or defensive deep-copy graphs.
- [x] The child returns bounded calculation data; the supervisor validates the current fence before staging and atomically publishing one immutable Result.
- [x] The child waits for the supervisor's terminal acknowledgement, exits at Attempt end, and is never reused by another Attempt.
- [x] Loss of the supervisor connection causes the child to exit without continuing calculation or publishing anything.
- [x] Market-only, financial-only, and composite short Formulae produce canonical bytes identical to the accepted reference execution contract.
- [x] A stale child cannot publish after another owner advances the fence.
- [x] Integration tests use an actual child process, PostgreSQL, and RustFS and prove that the child cannot mutate owned durable state.
- [x] The old direct whole-Run kernel call from the Worker path and any second execution route are deleted in the same change.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 02.
- Verification: `pnpm test` (487 Python + 25 Web), isolated PostgreSQL/RustFS
  integration run `20260817t185217z-81443-36974321` (158 + restart), and final-image
  browser run `20260817t185429z-82193-07b07f4c` (3/3).
- Final Spec and Standards reviews passed after closing lifecycle, fence-order,
  explicit columnar-route, bounded Parquet-batch, and financial Arrow/PIT findings.
