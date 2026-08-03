# 02 — Characterize the accepted quantitative behavior

**What to build:** Freeze the accepted Alpha, Label, Factor, Strategy, numeric,
ordering, Benchmark, and retained-result behavior before calculation code moves.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Deterministic cases cover the accepted public calculation boundaries.
- [x] Exact numeric, missing-value, ordering, Benchmark, and retained-window
  behavior is captured rather than approximated.
- [x] Run-once and session-by-session reference inputs reach the same named
  research boundaries needed by later Kernel work.
- [x] Expected values come from accepted behavior and independent fixtures, not
  from copying the implementation under test.
- [x] This ticket changes no production calculation result.

**How to verify:**

- Run `uv run pytest -q tests/kernel` twice from a clean process and confirm the
  characterization results are deterministic.
- Review any updated expected values against the accepted domain contracts;
  unexplained quantitative changes fail the ticket.

## Comments

- Added `tests/kernel/test_characterization.py` with hard-coded accepted
  checksums and boundary values for Alpha, Labels, Factor, Strategy, numeric
  serialization, deterministic ordering, Benchmark treatment, and the compact
  retained Result projection. Expected outputs are constants rather than values
  calculated by a second reference implementation.
- Added the session-scoped `accepted_calculation_case` in
  `tests/kernel/conftest.py`. It generates deterministic canonical market input
  independently of the calculation assertions and exposes each named boundary
  needed by later `ResearchKernel.run` and `ResearchKernel.advance` work.
- The session-by-session proof recalculates every Factor day and advances
  Strategy metric state one Research Session at a time, then compares the named
  results canonically with the run-once result.
- TDD red: `uv run pytest -q tests/kernel/test_characterization.py` produced one
  passing independent edge case and two expected fixture-not-found errors.
- TDD green: the same command passed `3` tests after the fixture was added.
- Determinism verification: `uv run pytest -q tests/kernel` was run twice in
  separate pytest processes after final formatting; both runs passed all `26`
  tests (`11.26s` and `9.37s`).
- Production result: no file under `src/` changed in this ticket.
