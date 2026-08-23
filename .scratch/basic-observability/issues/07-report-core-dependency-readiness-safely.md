# 07 — Report Core dependency readiness safely

**What to build:** Give orchestration and operators a safe readiness response
that identifies whether PostgreSQL, RustFS, or the mounted Dataset Store is
unavailable, while preserving liveness as a dependency-free process check and
excluding Worker capacity from the API dependency contract.

**Blocked by:** 01 — Emit safe structured HTTP events

**Status:** ready-for-agent

- [ ] `GET /health/live` remains dependency-free and returns 200 when the API process can serve requests.
- [ ] `GET /health/ready` checks PostgreSQL, RustFS, and the mounted Dataset Store independently within bounded time.
- [ ] PostgreSQL readiness performs a minimal database round trip, RustFS readiness uses the established storage-availability boundary without listing private objects, and Dataset Store readiness proves only that the configured mounted root exists and is readable.
- [ ] A mounted and readable Dataset Store with no current Dataset Head is ready.
- [ ] Worker process presence, Worker role, queue depth, Dataset coverage, bootstrap completeness, Result presence, and Tracking Checkpoint presence are excluded from readiness.
- [ ] The route returns 200 only when all three dependencies are ready and 503 otherwise.
- [ ] Each response contains one overall status plus exactly one safe status and stable code for each dependency.
- [ ] Success codes are `POSTGRESQL_READY`, `RUSTFS_READY`, and `DATASET_STORE_READY`; failure codes are `POSTGRESQL_UNAVAILABLE`, `RUSTFS_UNAVAILABLE`, and `DATASET_STORE_UNAVAILABLE`.
- [ ] Responses contain no raw dependency error, DSN, endpoint, credential, bucket name, object key, or physical path.
- [ ] Neither liveness nor readiness creates routine HTTP completion events or repeated unchanged dependency logs.
- [ ] Real integration tests fail and recover each dependency independently, verify exact status/code combinations and bounded completion, and use condition polling rather than arbitrary sleep.
- [ ] Existing process-liveness orchestration continues to use liveness; the implementation does not broadly replace restart probes with dependency readiness.
- [ ] No readiness result creates or updates Product State or changes ResearchRun, DailyTrack, Data Refresh, or Worker behavior.

## Comments

- Parent: Basic Operational Observability.
