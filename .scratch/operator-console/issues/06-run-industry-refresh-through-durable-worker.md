# 06 — Run Industry Refresh through the durable Data Operator Worker

**What to build:** Let the Operator submit an Industry Refresh with an explicit
observation boundary and observe it complete through the same durable Worker,
validation, idempotency, and publication contract used by Web and CLI.

**Blocked by:** 04 — Run Market Refresh through the durable Data Operator Worker.

**Status:** ready-for-agent

- [ ] The Industry form accepts an explicit observation-through Research Session
  and uses the same validation contract as the private CLI.
- [ ] Password-confirmed submission creates an accepted Industry Data Refresh
  Operation with the exact editable idempotency key and returns before execution.
- [ ] Industry collection, validation, Canonical projection, and publication run
  inside the shared single-slot Data Operator Worker.
- [ ] Published, no-change, business-rejected, and infrastructure-failed outcomes
  are represented distinctly without exposing raw upstream or storage details.
- [ ] Console and CLI submission and inspection share one durable operation
  contract and return consistent targets, keys, states, and outcomes.
- [ ] The former synchronous one-shot Industry Refresh entry path is removed as a
  hard cut without a compatibility or fallback execution path.
- [ ] Real-PostgreSQL integration tests with versioned source replay cover
  idempotency, execution, publication, no change, validation rejection, and
  failure.
- [ ] A real browser test proves the explicit target, password confirmation,
  asynchronous acceptance, and visible terminal result.
