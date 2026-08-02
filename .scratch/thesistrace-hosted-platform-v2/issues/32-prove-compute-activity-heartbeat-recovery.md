# 32 — Prove Compute Activity Heartbeat Recovery

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Isolate the real long Compute Activity failure path and prove
Temporal heartbeat timeout and redelivery without also cycling the API, relay,
Data Worker, or publication path.

**Blocked by:** 29 — Prove Local Identity, Isolation, and Retained Product Health.

**Status:** ready-for-agent

- [ ] The gate creates a dedicated idempotent ResearchRun from the retained product witness and reacquires authentication whenever a long wait crosses token lifetime.
- [ ] The runner observes the production Compute Activity in its actual running state and confirmed Worker ownership before sending the deterministic hard-stop signal to only the active Compute Worker.
- [ ] The real production heartbeat timeout and Temporal redelivery occur, a restarted Compute Worker accepts a later attempt, and evidence records the attempt, timeout, redelivery, heartbeat, and terminal transition identities.
- [ ] Recovery produces exactly one complete authoritative result with no duplicate terminal domain transition, partial object, leaked Working Cache entry, or unfenced late result from the killed attempt.
- [ ] Cancellation and late-result fencing assertions cover the same Compute execution boundary without substituting a synthetic short timeout for the production heartbeat contract.
- [ ] The Compute Worker is restored, named health checks converge, the dedicated run is stable, and the post-gate state digest is recorded before success.
- [ ] The gate can be retried independently without re-running API/relay or Dataset Publication recovery, and failure preserves the exact Temporal and Worker state needed for diagnosis.
