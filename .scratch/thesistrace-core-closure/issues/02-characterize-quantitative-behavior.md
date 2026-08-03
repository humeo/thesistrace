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
- The session-by-session proof starts from an independently generated 600-session
  seed, then executes `156` one-session transitions. Every transition calculates
  Alpha, matures Labels, records Factor observations, advances Strategy and its
  Benchmark, and compares those named boundaries exactly with the run-once path.
  The complete final boundary state also has a fixed canonical SHA-256.
- The compact retained Result is frozen by its complete canonical SHA-256 plus
  exact first/last Strategy observations, first Rebalance, terminal-position
  ordering, and retained row counts. Equal-length content or ordering drift now
  fails the test.
- TDD red: the retained-result behavior assertion deliberately expected the
  placeholder digest `pending`; pytest failed at that assertion and reported
  the accepted canonical digest
  `cebf53e0c134ab0cdc6762e3f1af3e0cb9ce304d4ddf0ff8c8ae4a6fec6ded39`.
- TDD green: after recording the reviewed digest and full one-session boundary
  proof, `uv run pytest -q tests/kernel/test_characterization.py` passed all `3`
  tests.
- Determinism verification: `uv run pytest -q tests/kernel` was run twice in
  separate pytest processes after the review fixes; both runs passed all `26`
  tests (`12.20s` and `12.63s`).
- Production result: no file under `src/` changed in this ticket.
