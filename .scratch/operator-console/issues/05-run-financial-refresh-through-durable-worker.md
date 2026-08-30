# 05 — Run Financial Refresh through the durable Data Operator Worker

**What to build:** Let the Operator submit a Financial Refresh with the same
explicit collection boundary as the CLI and observe its complete, no-change, or
degraded result through the shared durable operation lifecycle.

**Blocked by:** 04 — Run Market Refresh through the durable Data Operator Worker.

**Status:** complete

- [x] The Financial form accepts an explicit observation-through Research
  Session and uses the same validation contract as the private CLI.
- [x] Password-confirmed submission creates an accepted Financial Data Refresh
  Operation with the exact editable idempotency key and returns before execution.
- [x] The existing Financial collection, Canonical projection, publication, and
  Dataset Head invariants execute inside the shared Data Operator Worker without
  a second Worker or synchronous Console request.
- [x] Published, no-change, business-rejected, and infrastructure-failed outcomes
  are represented distinctly and preserve safe counts needed for diagnosis.
- [x] Pending instruments or discovery gaps produce explicit degraded success,
  retain their counts and consequences, and do not trigger infrastructure retry.
- [x] The Console and CLI inspect the same durable receipt and cannot disagree on
  target, idempotency key, status, or publication outcome.
- [x] The former synchronous one-shot Financial Refresh entry path is removed as
  a hard cut without a compatibility or fallback execution path.
- [x] Real-PostgreSQL integration tests with versioned source replay cover
  publication, no change, pending instruments, discovery gaps, business
  rejection, failure, and idempotency.
- [x] A real browser test proves the explicit target, confirmation, accepted
  response, and degraded-success presentation.

## Implementation Plan

1. **Extend the existing receipt into the second shared-FIFO kind.** Hard-cut
   `data.refresh_operations` to admit `market` and `financial` rows with exactly
   one kind-specific target, preserve exact idempotency, and project one safe
   receipt containing target, lifecycle, publication result, diagnostic counts,
   and failure code. Keep the detailed Financial discovery/checkpoint tables as
   Worker-owned execution state, not as a second public operation lifecycle.
2. **Share one Financial request contract across Web and CLI.** Centralize the
   exact idempotency-key and ISO Research Session validation. Both entry points
   call the same asynchronous submission method, while the accepted receipt
   preserves the canonical observation-through Session and never selects one on
   the Operator's behalf.
3. **Dispatch Financial work inside the singleton Worker.** Let the existing
   global FIFO claim either kind and dispatch the Financial claim through the
   established CNINFO discovery, per-instrument Tushare collection, Canonical
   projection, composed-Generation validation, and Dataset Head publication
   path. Bind Financial publication and terminal receipt completion to the
   renewable shared claim so a stale owner cannot publish or complete work.
4. **Normalize Financial domain outcomes at the durable boundary.** Record
   complete publication, canonical no-change, degraded publication with pending
   instruments or discovery gaps, terminal business rejection, and retryable
   infrastructure failure distinctly. Persist only bounded counts and stable
   codes on the shared receipt; do not expose upstream evidence, manifests,
   paths, instrument identities, or raw failure text.
5. **Hard-cut synchronous Financial execution.** Make `refresh-financial`
   submit-and-return only, make `inspect-financial-refresh` read the shared safe
   receipt, and remove source construction or one-shot publication from those
   CLI paths. The existing always-running `worker` remains the only executor and
   receives live or versioned replay Financial sources alongside Market sources.
6. **Add the focused Console Financial flow.** Add an explicit freely entered
   observation-through Session, editable suggested Financial key, exact
   password confirmation, asynchronous accepted receipt, and polling of the
   same safe status endpoint. Present complete, no-change, degraded-pending,
   degraded-gaps, business-rejected, and infrastructure-failed states with
   non-color text and the diagnostic counts needed to understand consequence.
7. **Prove the hard cut at real seams.** Add real-PostgreSQL tests driven by a
   versioned Financial replay for shared FIFO, idempotency, publication,
   canonical no-change, pending instruments, discovery gaps, business rejection,
   infrastructure retry/failure, and safe inspection; add Auth/Core contract
   tests and a real Caddy browser flow. Run focused then full host, Auth,
   integration, browser, and image gates before independent Standards and Spec
   review/fix/re-review and this ticket's own commit.

## Verification

- `pnpm test`: Ruff and both typechecks passed; 903 Python tests, 167 Auth tests,
  and 126 Web tests passed on the final tree.
- `pnpm test:integration`: 402 main integration/acceptance tests passed with
  eight environment-selected tests deselected; all six isolated PostgreSQL and
  RustFS restart recovery phases plus 125 Auth PostgreSQL integration tests
  passed.
- `pnpm test:e2e`: 16/16 real-browser tests passed through Caddy in run
  `20260830t063054z-17100-49a09ca7`, including the freely entered Financial
  target, exact password confirmation, accepted receipt, response-loss recovery,
  complete/no-change/degraded/failed presentation, access loss, and focus
  restoration.
- `pnpm test:image-smoke`: passed for the final Core/Data Operator, Auth, and
  Caddy production images, including dependency restart, Worker crash recovery,
  and cold-volume reconstruction.
- Standards review: PASS after fixing safe receipt projection, Financial
  publication reconciliation after compare-and-swap, bounded failure codes,
  and Worker dispatch; the final focus and idempotent E2E stabilization delta
  was re-reviewed against repository test and accessibility rules with no
  findings.
- Spec review: PASS after verifying the shared FIFO, CLI-identical freely entered
  target, editable exact key, asynchronous proof boundary, Financial publication
  outcomes, hard cut, safe inspection, and real-browser lifecycle; the final
  delta did not change the ticket contract.
- `git diff --check`: passed on the final unstaged tree before commit.
