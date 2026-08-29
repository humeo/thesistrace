# 05 — Run Financial Refresh through the durable Data Operator Worker

**What to build:** Let the Operator submit a Financial Refresh with the same
explicit collection boundary as the CLI and observe its complete, no-change, or
degraded result through the shared durable operation lifecycle.

**Blocked by:** 04 — Run Market Refresh through the durable Data Operator Worker.

**Status:** ready-for-agent

- [ ] The Financial form accepts an explicit observation-through Research
  Session and uses the same validation contract as the private CLI.
- [ ] Password-confirmed submission creates an accepted Financial Data Refresh
  Operation with the exact editable idempotency key and returns before execution.
- [ ] The existing Financial collection, Canonical projection, publication, and
  Dataset Head invariants execute inside the shared Data Operator Worker without
  a second Worker or synchronous Console request.
- [ ] Published, no-change, business-rejected, and infrastructure-failed outcomes
  are represented distinctly and preserve safe counts needed for diagnosis.
- [ ] Pending instruments or discovery gaps produce explicit degraded success,
  retain their counts and consequences, and do not trigger infrastructure retry.
- [ ] The Console and CLI inspect the same durable receipt and cannot disagree on
  target, idempotency key, status, or publication outcome.
- [ ] The former synchronous one-shot Financial Refresh entry path is removed as
  a hard cut without a compatibility or fallback execution path.
- [ ] Real-PostgreSQL integration tests with versioned source replay cover
  publication, no change, pending instruments, discovery gaps, business
  rejection, failure, and idempotency.
- [ ] A real browser test proves the explicit target, confirmation, accepted
  response, and degraded-success presentation.
