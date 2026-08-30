# 04 — Run Market Refresh through the durable Data Operator Worker

**What to build:** Let the Operator submit a Market Refresh from the Console and
observe one durable operation progress to publication or no change through the
same always-running Worker and application service used by the private CLI.

**Blocked by:** 02 — Secure Invitation mutations with Operator Proof.

**Status:** complete

- [x] The Market form accepts the same explicit timezone-aware `as-of` value and
  backend validation as the private CLI; the server never silently selects a
  target date.
- [x] The form suggests a kind-and-time-based idempotency key, permits editing,
  and displays the exact accepted key in subsequent operation state.
- [x] The Core mutation consumes an Operator Proof through bounded internal Auth
  verification; Core and the Worker never receive the Operator's password.
- [x] Successful submission durably creates a Market Data Refresh Operation in
  `accepted` state and returns without waiting for collection or publication;
  persistence failure never reports acceptance.
- [x] One always-running, single-slot Data Operator Worker claims and executes the
  Market operation and records a safe terminal publication, no-change, or failure
  outcome.
- [x] The Console shows enough immediate state to distinguish accepted, running,
  published, no change, and failed without exposing upstream bodies, secrets,
  manifests, or object paths.
- [x] Reusing an idempotency key with the same canonical request returns the same
  operation; reusing it for different input is rejected without duplicate work.
- [x] Console and CLI submissions use the same durable operation and validation
  services, and the obsolete manually invoked Market worker path is removed as a
  hard cut rather than kept as a fallback.
- [x] Real-PostgreSQL and deterministic-replay integration tests cover submission,
  idempotency, claim, execution, publication, no change, failure, and proof
  rejection.
- [x] A real browser test proves password-confirmed submission and asynchronous
  status progression through the same-origin application.

## Implementation Plan

1. **Turn the Market receipt table into the first slice of the shared FIFO.**
   Add an explicit `market` kind to each durable receipt, permit multiple
   accepted rows, and enforce one globally running row in PostgreSQL. Keep the
   existing 15-minute fenced claim, 30-second heartbeat, three-attempt recovery,
   publication reconciliation, and safe terminal outcomes; submission and
   inspection continue to return only the durable receipt projection.
2. **Share one exact Market request contract between Web and CLI.** Centralize
   validation of the trimmed idempotency key and freely entered timezone-aware
   `as-of` string. Both entry points pass the normalized instant to the same
   `DataRefreshService`, while the proof remains bound to the exact submitted
   strings and the accepted receipt preserves the exact key plus canonical
   target.
3. **Consume the cross-service proof at the Auth boundary.** Extend the existing
   60-second Operator Proof with `data.refresh.market.submit` request binding and
   a private Auth consumption endpoint. Auth rechecks the current singleton
   Operator and Login Session, atomically consumes the proof, and treats an
   identical duplicate delivery as the same authorization receipt; mismatches,
   expiry, replay for another request, ordinary Researchers, and Auth outage
   fail closed. Core receives the opaque proof but never the password.
4. **Expose the narrow Core Market operation API.** Add an Operator-authorized
   same-origin submission route and an Operator-authorized exact-key status
   route. Submission validates before proof consumption, persists before
   returning `accepted`, maps known conflicts safely, and exposes no manifest,
   object path, upstream body, token, or internal exception. Wire the same
   service into the Core runtime that the CLI and Worker use.
5. **Hard-cut the manual Market worker.** Replace `work-refresh` with a `worker`
   process whose default mode continuously polls and whose explicit `--once`
   plus replay mode is reserved for deterministic qualification. Add exactly one
   always-running `data-operator-worker` Compose service with writable Canonical
   and Benchmark mounts; deliver `THESISTRACE_TUSHARE_TOKEN` only to that
   service and update the private runbook and lifecycle contracts.
6. **Add the focused Operator Data flow.** Register `/operator/data` beside the
   Researcher Console, add an editable text `as-of` field and kind/time suggested
   key, and use an accessible password-confirmation dialog that shows the exact
   target, key, and effect. After acceptance, show the exact receipt and poll
   only that visible non-terminal operation until published, no change, or
   failed; keep the password and proof out of browser persistence.
7. **Prove the end-to-end boundary at real seams.** Add Auth PostgreSQL tests for
   exact proof consumption and duplicate delivery, Core/Data PostgreSQL tests
   for queued idempotent submission, single claim and all Market outcomes,
   entrypoint tests for the worker hard cut, API contract tests for ordinary
   `404` and unavailable Auth, and a real Caddy browser flow driven by the
   versioned replay Worker. Run host, Auth integration, E2E, and Production
   Caddy gates, then complete Standards and Spec review/fix/re-review before the
   independent Ticket 04 commit.

## Verification

- `pnpm test`: Ruff and both typechecks passed; 891 Python tests, 165 Auth tests,
  and 117 Web tests passed on the final tree.
- `pnpm test:integration`: 376 main integration/acceptance tests, six isolated
  PostgreSQL/RustFS restart recovery tests, and 124 Auth PostgreSQL integration
  tests passed, including both stale-worker publication-window regressions.
- `pnpm test:e2e`: 16/16 real-browser tests passed through Caddy, including
  password-confirmed Market submission, durable Worker progression, exact
  response-loss reconciliation, stale-response fencing, and focus restoration.
- `pnpm test:image-smoke`: passed for the final Core/Data Operator, Auth, and
  Caddy production images, including dependency outage and restart recovery.
- Standards review: PASS after owner/lease publication fencing, exact
  response-loss reconciliation, stale browser epoch isolation, and focus timing
  fixes; the independent 42/42 changed-file security scan reported zero findings.
- Spec review: PASS after verifying the CLI-equivalent free-form target, editable
  exact key, proof boundary, queued receipt, singleton FIFO Worker, hard cut,
  safe status projection, and real-browser lifecycle.
