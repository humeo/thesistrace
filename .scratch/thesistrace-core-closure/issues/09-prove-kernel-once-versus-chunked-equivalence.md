# 09 — Prove Kernel once-versus-chunked equivalence

**What to build:** Prove that processing the same canonical sessions once or in
chunks produces canonically identical Kernel state at the same boundary.

**Blocked by:** 08.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Run-once and multi-Advance processing produce canonically identical
  calculation state.
- [x] The proof covers Label maturation, Factor aggregation, Strategy state,
  Benchmark state, numeric serialization, and retained windows.
- [x] The comparison uses the same immutable origin, contracts, and ordered
  sessions.
- [x] A deliberate semantic mismatch identifies the first divergent boundary.
- [x] Equivalence does not rely on a second reference engine maintained beside
  the production Kernel.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
uv run pytest -q tests/kernel
```

The suite must compare one batch with multiple Advance chunks by canonical
equality rather than tolerance-only comparison. It must also inject one
controlled semantic mismatch and assert the exact first divergent calculation
boundary automatically; no manual fixture edit is part of verification.

## Comments

- TDD red: the new proof failed at collection because the pure Kernel did not
  yet own an `equivalence` boundary.
- The fixed 756-session Run is the shared immutable seed. The once path applies
  all four later sessions in one Advance; the chunked path applies those same
  ordered sessions as `1 + 2 + 1`. Their complete `KernelState` values and
  canonical evidence bytes are exactly equal at the same final boundary.
- Complete state evidence includes the pinned canonical input and contracts,
  origin, session count, boundary, Alpha, Labels, Factor, Strategy/Benchmark,
  and the pre-terminal resumable Strategy state. The proof also asserts the
  504-session Label and Factor retained windows.
- Exact binary64 and Decimal comparison plus first-divergence traversal now
  belong to `research_kernel.equivalence`. Product Tracking imports those same
  callable objects, so no second equality implementation exists.
- The negative proof mutates one penultimate `benchmark_nav` value in copied
  evidence and asserts the exact indexed JSON path returned as the first
  divergence; verification requires no manual file change.
- The exact `How to verify` command passed `67 passed, 1 warning` in `139.55s`.
- Independent review: `Standards: PASS`, `Spec: PASS`, with no blocking
  findings. The reviewer separately confirmed state advanced from 756 to 760
  sessions and that the proof is not comparing two empty transitions.
- Final repository gate: `make check` passed with Ruff clean, `481 passed,
  34 skipped, 2 warnings` in Python (`456.13s`), Web typecheck/build green, and
  narrow/desktop Playwright acceptance passing in `29.0s` and `30.5s`.
