# 09 — Prove Kernel once-versus-chunked equivalence

**What to build:** Prove that processing the same canonical sessions once or in
chunks produces canonically identical Kernel state at the same boundary.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] Run-once and multi-Advance processing produce canonically identical
  calculation state.
- [ ] The proof covers Label maturation, Factor aggregation, Strategy state,
  Benchmark state, numeric serialization, and retained windows.
- [ ] The comparison uses the same immutable origin, contracts, and ordered
  sessions.
- [ ] A deliberate semantic mismatch identifies the first divergent boundary.
- [ ] Equivalence does not rely on a second reference engine maintained beside
  the production Kernel.

**How to verify:**

- Run `uv run pytest -q tests/kernel` and confirm once-versus-chunked cases pass
  by canonical equality rather than tolerance-only comparison.
- Mutate one controlled fixture expectation and confirm the evidence reports the
  first divergent calculation boundary.

## Comments
