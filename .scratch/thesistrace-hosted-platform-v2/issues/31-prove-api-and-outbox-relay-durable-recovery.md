# 31 — Prove API and Outbox Relay Durable Recovery

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Prove the short durable boundary from an idempotent product
request through PostgreSQL outbox persistence to exactly one Temporal workflow.
Keep this independent from Worker heartbeat and Dataset Publication failures.

**Blocked by:** 29 — Prove Local Identity, Isolation, and Retained Product Health.

**Status:** ready-for-agent

- [ ] The gate creates dedicated rerun inputs from the retained product witness and reacquires a fresh User token instead of using authentication material from an earlier gate.
- [ ] With the API unavailable at a deterministic point, concurrent retries using one idempotency key recover to exactly one durable ResearchRun and one accepted response identity after the API returns.
- [ ] With the outbox relay stopped, the accepted request remains durably queued and no workflow starts; restarting the relay starts exactly one production Temporal workflow for that outbox record.
- [ ] Duplicate delivery, relay restart, and client retry do not create duplicate workflows, domain results, outbox terminal transitions, or authoritative objects.
- [ ] Fault injection uses bounded, observable readiness conditions rather than a fixed millisecond race, and it never stops a Compute/Data Worker or waits through an Activity heartbeat timeout.
- [ ] The API and relay are restored to their canonical Core Session state, the dedicated run reaches a stable terminal state, and the output state digest and exact outbox/workflow evidence are recorded.
- [ ] The gate can be retried independently in the same compatible session without re-running identity provisioning or the retained product-health gate.
