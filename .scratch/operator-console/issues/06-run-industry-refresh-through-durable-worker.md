# 06 — Run Industry Refresh through the durable Data Operator Worker

**What to build:** Let the Operator submit an Industry Refresh with an explicit
observation boundary and observe it complete through the same durable Worker,
validation, idempotency, and publication contract used by Web and CLI.

**Blocked by:** 04 — Run Market Refresh through the durable Data Operator Worker.

**Status:** complete

- [x] The Industry form accepts an explicit observation-through Research Session
  and uses the same validation contract as the private CLI.
- [x] Password-confirmed submission creates an accepted Industry Data Refresh
  Operation with the exact editable idempotency key and returns before execution.
- [x] Industry collection, validation, Canonical projection, and publication run
  inside the shared single-slot Data Operator Worker.
- [x] Published, no-change, business-rejected, and infrastructure-failed outcomes
  are represented distinctly without exposing raw upstream or storage details.
- [x] Console and CLI submission and inspection share one durable operation
  contract and return consistent targets, keys, states, and outcomes.
- [x] The former synchronous one-shot Industry Refresh entry path is removed as a
  hard cut without a compatibility or fallback execution path.
- [x] Real-PostgreSQL integration tests with versioned source replay cover
  idempotency, execution, publication, no change, validation rejection, and
  failure.
- [x] A real browser test proves the explicit target, password confirmation,
  asynchronous acceptance, and visible terminal result.

## Implementation Plan

1. **Admit Industry into the existing shared receipt and FIFO.** Hard-cut
   `data.refresh_operations` to accept `industry` beside Market and Financial,
   reuse the explicit observation-through Session target, and represent accepted,
   running, published, no-change, business-rejected, and infrastructure-failed
   states without adding a parallel public lifecycle. Keep the detailed Industry
   receipt as Worker-owned recovery state only.
2. **Share one exact request contract across CLI, Auth, Core, and Web.** Add a
   centralized Industry key and ISO Research Session validator, bind the
   single-use Operator Proof to the exact target and key, and make both CLI and
   same-origin HTTP submission call `DataRefreshService.submit_industry` and
   return the same durable receipt before execution.
3. **Fence the existing Industry pipeline to the shared claim.** Dispatch an
   Industry claim from the singleton Worker through the established Tushare
   collection, validation, immutable Family materialization, composition, and
   Dataset Head compare-and-swap path. Add ownership checks around collection,
   publication, and completion, with the publication guard in the same
   PostgreSQL transaction as Head movement so an expired owner cannot publish.
4. **Normalize completion and recovery at the durable boundary.** Detect exact
   Industry Family no-change without moving Head, project only bounded stable
   failure codes, reconcile a Head move or detailed receipt completion after a
   crash, retry infrastructure loss on the shared operation, and leave Industry
   validation failures terminal as business rejection.
5. **Hard-cut the synchronous command and select deterministic Worker sources.**
   Make `refresh-industry` submit-only and `inspect-industry-refresh` inspect the
   shared safe receipt. Give the always-running Worker the live Industry source
   and an exact observation-target replay selector; remove source construction
   and one-shot publication from the CLI path without compatibility or fallback.
6. **Add the focused Console Industry flow.** Add a freely entered Research
   Session, editable suggested Industry key, exact password confirmation,
   asynchronous accepted receipt, response-loss reconciliation, and textual
   published/no-change/business-rejected/infrastructure-failed presentation in
   the existing Operator Data surface with deterministic validation focus.
7. **Prove the cut at real seams.** Add unit and Auth/Core contract tests,
   real-PostgreSQL shared-FIFO and Industry replay tests for idempotency,
   publication, no change, validation rejection, infrastructure failure, claim
   fencing, and recovery, plus a real Caddy browser flow. Run focused and full
   host, integration, E2E, and production-image gates, complete Standards and
   Spec review/fix/re-review, update this tracker, and commit Ticket 06 alone.

## Verification

- `pnpm test`: Ruff and both typechecks passed; 909 Python tests, 168 Auth tests,
  and 132 Web tests passed on the final tree. The only warning was the existing
  local-lifecycle `forkpty` deprecation warning.
- `pnpm test:integration`: 407 main real-dependency tests passed with eight
  environment-selected tests deselected; all six isolated PostgreSQL/RustFS
  restart and recovery phases passed, followed by 126 Auth PostgreSQL/process
  integration tests.
- `pnpm test:e2e`: 16/16 real-browser tests passed through production Caddy in
  run `20260830t082728z-28460-5299ca86`, including the freely entered Industry
  target, exact password confirmation, asynchronous acceptance, actual Worker
  publication, Canonical no-change, business rejection, safe receipt, and
  ordinary-Researcher denial.
- `pnpm test:image-smoke`: passed for the final Core/Data Operator, Auth, and
  Caddy production images in the run beginning
  `20260830t083127z-30772-45ebb1e8`, including dependency restart, Worker crash
  recovery, cold-volume reconstruction, and security-response probes.
- Standards review: PASS after removing a redundant Industry publication lock
  that exhausted the bounded PostgreSQL pool, making publication reconciliation
  converge under a concurrent completion, and binding the browser assertion to
  the labelled receipt field. Re-review found no remaining ownership, locking,
  transaction, authorization, error-projection, accessibility, or cleanup
  findings.
- Spec review: PASS after verifying the CLI-identical freely entered target,
  editable exact key, one-time password proof, shared FIFO, Worker-owned
  execution, Canonical-only no-change, distinct safe outcomes, synchronous-path
  hard cut, replay coverage, and real-browser lifecycle. Re-review found no
  remaining acceptance gaps.
- `git diff --check`: passed on the final unstaged tree before commit.
