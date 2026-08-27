# 04 — Core Researcher and Research Ownership hard cut

**Status:** ready-for-agent

**Blocked by:** 01, 02, 03

## Goal

Atomically cut FastAPI and every private Core resource from ownerless state to
authenticated Researcher ownership while keeping Worker execution independent
of Auth.

## Scope

- Add the `researcher` module and `researchers` schema. Implement idempotent
  authenticated `POST /api/researcher/bootstrap` that creates the Researcher,
  Default Folder, and Batch Research Folder in one transaction.
- Change the complete Core schema snapshot to seven schemas. Reset ownerless
  Product State; preserve mounted Canonical Data. Add no migration or synthetic
  owner.
- Give Research Folder composite `(researcher_id, id)` identity. Add explicit
  Researcher ID to ResearchRun, Research Batch, and DailyTrack and enforce
  same-owner Folder, Batch-item Run, and seed-Run Track relationships with
  database constraints.
- Scope admission, cancellation, start-tracking, retry, and stop receipts by
  `(researcher_id, request_id)`.
- Thread explicit Researcher context through all service list, detail, create,
  organize, cancel, delete, start, retry, and stop interfaces. Filter before
  checking state so cross-Researcher IDs return `404`.
- Bind pagination cursors to Researcher and all filters; mismatch is `400`.
- Add FastAPI authentication middleware/dependency using the private Auth
  verifier and original Cookie. Map invalid/inactive to `401` and Auth
  transport/timeout/schema failure to `503`.
- Require exact public Origin on POST/PATCH/DELETE and JSON on body-bearing
  writes without enabling browser CORS.
- Protect Data Overview and Alpha Catalog as shared authenticated resources.
- Add Auth to Core readiness, not liveness. Keep every Worker free of Auth and
  active-state checks.
- Add a Core-owned private inspection that counts active DailyTracks for one
  Researcher so deployment access tooling can report without cross-schema
  grants or implicit Stop.
- Preserve authorized PostgreSQL-to-RustFS publication reads without exposing
  object keys or manifests to the browser.

## Acceptance criteria

- [ ] Bootstrap is transactional and idempotent under concurrent calls.
- [ ] Two Researchers each own `folder_default` and `folder_batch_research`.
- [ ] Same request ID is independent across Researchers and conflicting only
      within one Researcher scope.
- [ ] Folder, Run, Batch, and Track operations succeed for the owner and return
      `404` for the other Researcher, including known IDs.
- [ ] Database constraints reject every constructed cross-owner relationship.
- [ ] Invalid Session is `401`; Auth unavailable/timeout/malformed is `503`;
      own-resource forbidden state remains `403` only where specified.
- [ ] Workers continue and publish admitted work after Researcher Deactivation.
- [ ] Existing ownerless Product State and legacy schema fingerprint are refused;
      Canonical Data remains readable after reset.
- [ ] Core cannot read Auth tables and accepts no trusted identity header, JWT,
      bearer, or API key.

## Verification

- Real-PostgreSQL schema, transaction, constraint, receipt, cursor, and
  concurrency integration tests.
- Core HTTP contract tests with deterministic Auth verifier transport plus one
  real Auth/Core integration suite.
- Worker recovery/publication tests across Deactivation and Session revocation.
- Existing acceptance suites rewritten with explicit Researcher setup; no
  default-user fixture in production code.
- `mise exec -- pnpm test`, `mise exec -- pnpm test:integration`, and the
  relevant Core acceptance gate.

## Delivery

This ticket is intentionally one large hard-cut commit because intermediate
ownerless compatibility would violate the security boundary. Do not split it by
adding nullable owners, default Researchers, dual keys, legacy cursor readers,
or conditional authentication.

## Comments
