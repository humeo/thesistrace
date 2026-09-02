# Bound admission by the execution Chunk

**Status:** complete

Measure the actual Universe member union for candidate context slices, choose the
widest legal shared Chunk, and freeze that choice into every child execution plan.

## Acceptance

- Total history length does not change estimated peak memory.
- Rotating membership is priced by the slice union, not daily maximum membership.
- A Batch is rejected only when no one-session execution slice fits.

## Comments

- 2026-09-03: Implemented and committed in `141594d` and `15f2673`.
  Regression coverage proves actual slice-union pricing, one-session rejection,
  a shared frozen Chunk plan, and history-length-independent peak estimation.
  The full release gate passed at `d2adced`.
