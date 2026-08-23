# 07 — Report Core dependency readiness safely

**What to build:** Give orchestration and operators a safe readiness response
that identifies whether PostgreSQL, RustFS, or the mounted Dataset Store is
unavailable, while preserving liveness as a dependency-free process check and
excluding Worker capacity from the API dependency contract.

**Blocked by:** 01 — Emit safe structured HTTP events

**Status:** complete

- [x] `GET /health/live` remains dependency-free and returns 200 when the API process can serve requests.
- [x] `GET /health/ready` checks PostgreSQL, RustFS, and the mounted Dataset Store independently within bounded time.
- [x] PostgreSQL readiness performs a minimal database round trip, RustFS readiness uses the established storage-availability boundary without listing private objects, and Dataset Store readiness proves only that the configured mounted root exists and is readable.
- [x] A mounted and readable Dataset Store with no current Dataset Head is ready.
- [x] Worker process presence, Worker role, queue depth, Dataset coverage, bootstrap completeness, Result presence, and Tracking Checkpoint presence are excluded from readiness.
- [x] The route returns 200 only when all three dependencies are ready and 503 otherwise.
- [x] Each response contains one overall status plus exactly one safe status and stable code for each dependency.
- [x] Success codes are `POSTGRESQL_READY`, `RUSTFS_READY`, and `DATASET_STORE_READY`; failure codes are `POSTGRESQL_UNAVAILABLE`, `RUSTFS_UNAVAILABLE`, and `DATASET_STORE_UNAVAILABLE`.
- [x] Responses contain no raw dependency error, DSN, endpoint, credential, bucket name, object key, or physical path.
- [x] Neither liveness nor readiness creates routine HTTP completion events or repeated unchanged dependency logs.
- [x] Real integration tests fail and recover each dependency independently, verify exact status/code combinations and bounded completion, and use condition polling rather than arbitrary sleep.
- [x] Existing process-liveness orchestration continues to use liveness; the implementation does not broadly replace restart probes with dependency readiness.
- [x] No readiness result creates or updates Product State or changes ResearchRun, DailyTrack, Data Refresh, or Worker behavior.

## Comments

- Parent: Basic Operational Observability.
- Implementation: added a dependency-free liveness route and a safe readiness
  snapshot whose PostgreSQL, RustFS, and mounted-root probes execute in parallel
  isolated subprocesses under one two-second deadline. Timed-out probes are
  killed without a blocking reap and retained per dependency to prevent repeated
  unbounded children if kernel I/O cannot exit.
- Review: initial independent reviews found that client-local timeouts did not
  bound network or mounted-filesystem hangs, cleanup could wait forever after
  `SIGKILL`, and dependency tests replaced clients instead of stopping the same
  real services. All were fixed; final independent Standards and Spec
  re-reviews were clean.
- Verification: Ruff and diff-check passed; focused deadline, health-event, and
  architecture lanes 11 passed; a fresh isolated real PostgreSQL/RustFS/Dataset
  Store fail-and-recover lane passed on one API runtime; complete backend fast
  lane 540 passed with 5 existing warnings; Web typecheck passed; Web shell lane
  56 passed. Both one-off dependency containers were verified healthy after
  recovery and removed.

## Plan

1. Add bounded, read-only availability seams at the dependency owners: a
   minimal PostgreSQL round trip, RustFS availability that safely handles all
   established transient client failures without listing private objects, and
   a mounted Dataset Store root readability check that does not inspect Head or
   Dataset content.
2. Compose those three seams in one Core readiness reader with a closed, stable
   response: one overall status and exactly one `status`/`code` pair per
   dependency, with no raw errors or configuration values and no state writes or
   routine logs.
3. Expose `GET /health/ready` from the existing Core runtime, returning 200 only
   when all dependencies are ready and 503 otherwise; preserve dependency-free
   `/health/live`, health-event suppression, and the Compose liveness probe.
4. Add real-dependency HTTP integration coverage for all-ready with an empty
   Dataset Head and independent PostgreSQL, RustFS, and mounted-root failures and
   recovery, including exact response shape, no emitted events, and bounded
   completion; add focused boundary and unit coverage for safe transient errors.
5. Run focused readiness, architecture, Ruff, complete fast backend, real
   integration and Web gates; complete independent Standards and Spec reviews,
   fix and re-review, update this tracker, and create one Ticket 07 commit.
