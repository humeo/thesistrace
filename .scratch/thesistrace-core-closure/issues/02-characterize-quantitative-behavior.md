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

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu

uv run pytest -q tests/kernel
uv run pytest -q tests/kernel
git diff --exit-code de7a4e4...HEAD -- src/
```

Both pytest processes must pass with the same `26 passed` result. The final
command compares the complete Ticket 02 range with its fixed pre-ticket base
and proves that this characterization ticket did not change production
calculation code. Any future expected-value update must be justified against
the accepted domain contracts in this ticket; an unexplained quantitative
change fails verification.

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
  separate pytest processes after the final review fix; both runs passed all
  `26` tests (`68.47s` and `66.91s`).
- Review round 2 found one low-priority duplicate canonical-window helper in the
  characterization test. It now composes the production-owned
  `slice_canonical_through` and `slice_canonical_range` boundaries instead of
  maintaining a third table list in test code.
- Final review found that the first production-code proof checked only the
  working tree. The ticket now compares `de7a4e4...HEAD`, so already committed
  `src/` changes cannot escape the guard.
- Production result: no file under `src/` changed in this ticket.
- Final repository gate: `make check` passed with Ruff clean, `427 passed,
  20 skipped` in Python (`358.50s`), Web typecheck/build green, and the narrow
  and desktop Playwright flows passing in `27.8s` and `27.5s` respectively.
