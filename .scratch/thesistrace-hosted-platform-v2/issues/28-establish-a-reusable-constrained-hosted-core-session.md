# 28 — Establish a Reusable Constrained Hosted Core Session

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Establish the one disposable 2C4G Core Session that later
product and recovery gates reuse. Stage an exact release once, start only the
required production seams, and expose an opaque, fingerprinted session context
without yet claiming product acceptance.

**Blocked by:** 27 — Resume Only the Next Compatible Local Acceptance Gate.

**Status:** resolved

- [x] An explicit reset creates a new state epoch and uniquely named disposable Compose project, networks, volumes, evidence directory, and service credentials without touching the developer's normal project.
- [x] The exact Release Bundle, including Web and edge artifacts, is built or selected once and recorded with source, image, asset, migration, Compose, and configuration digests. A downstream gate cannot rebuild or mutate the staged release without invalidating the session.
- [x] The core profile uses pinned production images, migrations, roles, networks, and service implementations, with one Compute Worker, a separate Data Worker, Compute Workers 2–4 disabled, and the observability profile disabled.
- [x] InsForge-compatible local authentication/bootstrap, PostgreSQL, Temporal, API, outbox relay, edge, storage, and required workers reach named health and readiness conditions under bounded waits, with resource samples captured during convergence.
- [x] Restarting the same compatible Core Session is idempotent and does not reset authoritative state or rebuild the release; any fingerprint mismatch is refused with an actionable reset instruction.
- [x] The gate returns only opaque session and infrastructure identifiers required by later gates, records no launch claim, and does not create the two-user product witness assigned to ticket 29.
- [x] Success may stop the session only under explicit cleanup policy; failure preserves its exact state. A guarded cleanup removes only resources owned by this Core Session.

**2C4G evidence:** Core first converged in 968.1 seconds. A same-volume,
same-bundle retry reused run `403e2afc-feb7-415f-8b15-1c8d8917e95d` and state
epoch `d6e58f52-3fb4-4ee7-b9ac-99bba203a910`, passed in 64.152 seconds, and
preserved runtime digest `4dcf259492c8921b852507e0b82bf6ecaf2085744da8fe58a16277e632b44d4d`.
