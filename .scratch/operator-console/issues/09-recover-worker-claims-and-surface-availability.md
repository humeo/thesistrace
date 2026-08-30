# 09 — Recover Worker claims and surface availability

**What to build:** Make every Data Refresh kind recover safely from Worker loss
and show the Operator whether accepted work is actively serviceable, without
confusing durable submission with processing or publication.

**Blocked by:** 07 — Expose unified Dataset Operational Status.

**Status:** complete

- [x] Every claim uses a 15-minute lease renewed by a 30-second heartbeat, and
  only the current fenced owner may publish or complete the operation.
- [x] An expired infrastructure claim is reclaimed on the same operation for at
  most three attempts; exhaustion becomes terminal `RETRY_EXHAUSTED`.
- [x] Recovery reconciles whether publication completed before a crash before
  performing further collection or publication, preventing a duplicate visible
  Dataset Head effect.
- [x] Market, Financial, and Industry operations all obey the same claim,
  heartbeat, fencing, recovery, and attempt policy.
- [x] Business rejection and Financial degraded success are terminal domain
  outcomes and are never retried as infrastructure loss.
- [x] A successfully persisted submission remains accepted while the Worker is
  unavailable, and the Console shows an explicit Worker-unavailable warning;
  persistence failure remains a rejected submission.
- [x] The status view safely exposes running phase, attempt, last heartbeat, and
  availability without exposing a secret or raw diagnostic payload.
- [x] A missing or placeholder Tushare Secret prevents Worker startup, and the
  secret is not delivered to Auth, Core API, Web, PostgreSQL, or browser state.
- [x] Controlled-clock, real-PostgreSQL integration tests cover lost heartbeat,
  fencing, reclaim, publication-before-crash reconciliation, three-attempt
  exhaustion, unavailable submission, and recovery after restart without sleep.
- [x] A real browser test proves accepted-with-warning, recovery to processing,
  attempt visibility, and terminal exhaustion copy.

## Implementation Plan

1. Preserve the existing durable Refresh execution contract and add focused
   real-PostgreSQL regression coverage for the already-shared Market,
   Financial, and Industry lease, heartbeat, fencing, reconciliation, and
   three-attempt recovery invariants. Drive expiry and crash boundaries by
   explicit database state changes and bounded condition polling, never sleep.
2. Add one hard-cut, singleton Data Operator Worker lease to the current Data
   schema. Acquire it only after database, mounts, source configuration, and
   live Tushare credentials are valid; renew it independently during both idle
   polling and long-running Refresh work; release it on orderly shutdown; and
   let an expired lease be replaced after an ungraceful stop. Do not add a
   migration, compatibility path, second-worker mode, or alternate executor.
3. Extend Dataset Operational Status with a bounded Worker projection containing
   only `available` and `last_heartbeat_at`. Derive availability against the
   database clock, keep submissions independent of that projection, and prove
   that a persisted operation remains `accepted` while no live Worker lease
   exists while persistence errors still reject the request.
4. Validate live Worker Tushare configuration before entering the processing
   loop, rejecting missing, development, test, angle-bracket, and other
   placeholder tokens without echoing them. Extend architecture and production
   image assertions so the token remains absent from Auth, Core API, Web,
   PostgreSQL, and browser-visible state while replay workers remain
   deterministic and offline.
5. Extend the strict Web decoder and Operator Dataset view with an accessible,
   explicit Worker-unavailable warning and Worker heartbeat copy. Keep visible
   accepted/running or unavailable work on the existing five-second polling
   path, and add component tests plus a real Caddy browser flow for
   accepted-with-warning, Worker recovery, attempt/phase visibility, and
   terminal `RETRY_EXHAUSTED` copy.
6. Run the narrow Python, TypeScript, architecture, integration, and browser
   tests first, then the repository test gate and production image smoke. Review
   the Ticket 09 diff for Standards and Spec separately, fix every finding,
   rerun affected gates, mark this issue complete, update the local tracker,
   and commit Ticket 09 as its own acceptance unit.

## Verification

- Final host gate: Ruff and both typechecks passed; 928 Python tests, 171 Auth
  tests, and 147 Web tests passed. The sole warning was the existing
  local-lifecycle `forkpty()` deprecation warning. Auth's first sandboxed run
  failed because the sandbox denied the Resend fake's loopback listener; the
  same suite passed 171/171 with the required local-listener permission.
- Real-dependency run `20260830t132344z-92284-225526ff`: 415 primary PostgreSQL
  and RustFS tests passed with eight marker-selected tests deferred, followed by
  all six independent database/dependency restart phases. The isolated Compose
  project, network, and mutable volumes were removed.
- Real Caddy browser run `20260830t134435z-21171-7ee85e0f`: all 16 E2E tests
  passed, including Worker unavailable with a durably accepted receipt,
  recovery of that same receipt from attempt one to attempt two, Worker
  availability, terminal attempt-three `RETRY_EXHAUSTED` copy, and the existing
  singleton Operator access boundary. The first final-tree run exposed and led
  to fixing a test-state conflict with the one-running-Refresh invariant; the
  clean rerun used a fresh project and passed without retries.
- Production Image Smoke run `20260830t134928z-24126-d30087ab`: every phase
  passed, including final image construction, secret-scope inspection, Worker
  health, long execution, Worker loss/recovery, database and RustFS restart,
  persisted state, empty-volume reset, bounded evidence, and MCP HTTP/stdio.
  Runtime-secret cleanup, Compose cleanup, and the overall run all reported
  status zero.
- Standards review fixed fail-open container secret inspection, rejection of the
  repository's known test token and whitespace-normalized secrets, exact
  last-heartbeat semantics on graceful Worker release, accurate interrupted
  running-work copy, and deterministic E2E cleanup of the recovered receipt.
  Re-review found no remaining lifecycle, secret-handling, status-projection,
  accessibility, cleanup, or `DESIGN.md` finding.
- Spec review: PASS. Existing real-PostgreSQL coverage continues to prove the
  shared Market/Financial/Industry operation lease, fencing, reconciliation,
  retry ceiling, and terminal domain outcomes; new coverage proves singleton
  Worker presence, accepted-without-Worker behavior, safe availability, strict
  live-secret startup, actual container restart, visible attempts, and terminal
  exhaustion. Re-review found no remaining acceptance gap.
- `git diff --check`: passed on the final unstaged tree before commit.
