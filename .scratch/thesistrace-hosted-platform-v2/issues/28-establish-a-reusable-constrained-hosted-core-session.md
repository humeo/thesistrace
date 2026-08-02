# 28 — Establish a Reusable Constrained Hosted Core Session

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Establish the one disposable 2C4G Core Session that later
product and recovery gates reuse. Stage an exact release once, start only the
required production seams, and expose an opaque, fingerprinted session context
without yet claiming product acceptance.

**Blocked by:** 27 — Resume Only the Next Compatible Local Acceptance Gate.

**Status:** ready-for-agent

- [ ] An explicit reset creates a new state epoch and uniquely named disposable Compose project, networks, volumes, evidence directory, and service credentials without touching the developer's normal project.
- [ ] The exact Release Bundle, including Web and edge artifacts, is built or selected once and recorded with source, image, asset, migration, Compose, and configuration digests. A downstream gate cannot rebuild or mutate the staged release without invalidating the session.
- [ ] The core profile uses pinned production images, migrations, roles, networks, and service implementations, with one Compute Worker, a separate Data Worker, Compute Workers 2–4 disabled, and the observability profile disabled.
- [ ] InsForge-compatible local authentication/bootstrap, PostgreSQL, Temporal, API, outbox relay, edge, storage, and required workers reach named health and readiness conditions under bounded waits, with resource samples captured during convergence.
- [ ] Restarting the same compatible Core Session is idempotent and does not reset authoritative state or rebuild the release; any fingerprint mismatch is refused with an actionable reset instruction.
- [ ] The gate returns only opaque session and infrastructure identifiers required by later gates, records no launch claim, and does not create the two-user product witness assigned to ticket 29.
- [ ] Success may stop the session only under explicit cleanup policy; failure preserves its exact state. A guarded cleanup removes only resources owned by this Core Session.
