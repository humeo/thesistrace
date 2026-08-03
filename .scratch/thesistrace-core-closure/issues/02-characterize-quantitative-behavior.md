# 02 — Characterize the accepted quantitative behavior

**What to build:** Freeze the accepted Alpha, Label, Factor, Strategy, numeric,
ordering, Benchmark, and retained-result behavior before calculation code moves.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Deterministic cases cover the accepted public calculation boundaries.
- [ ] Exact numeric, missing-value, ordering, Benchmark, and retained-window
  behavior is captured rather than approximated.
- [ ] Run-once and session-by-session reference inputs reach the same named
  research boundaries needed by later Kernel work.
- [ ] Expected values come from accepted behavior and independent fixtures, not
  from copying the implementation under test.
- [ ] This ticket changes no production calculation result.

**How to verify:**

- Run `uv run pytest -q tests/kernel` twice from a clean process and confirm the
  characterization results are deterministic.
- Review any updated expected values against the accepted domain contracts;
  unexplained quantitative changes fail the ticket.

## Comments
