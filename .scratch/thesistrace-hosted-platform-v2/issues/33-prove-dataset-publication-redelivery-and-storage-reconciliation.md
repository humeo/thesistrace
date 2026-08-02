# 33 — Prove Dataset Publication Redelivery and Storage Reconciliation

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Isolate the Data Worker failure path and prove a real Dataset
Publication can be redelivered and reconcile staged storage into one authoritative
release without depending on Compute recovery.

**Blocked by:** 29 — Prove Local Identity, Isolation, and Retained Product Health.

**Status:** ready-for-agent

- [ ] The gate creates a dedicated idempotent Dataset Publication input from the retained product context and reacquires authentication for every stateful API interaction.
- [ ] While the Data Worker is stopped, the publication request remains durably accepted or queued according to the product contract; repeated submission with the same idempotency key does not create a second publication.
- [ ] After the Data Worker starts, the runner observes the production publication Activity in its actual running state and confirmed Worker ownership before hard-stopping only that Data Worker.
- [ ] The real heartbeat timeout and Temporal redelivery produce a later successful attempt and exactly one authoritative Dataset release, manifest, index transition, and terminal domain result.
- [ ] Staging keys, guards, manifests, object hashes, indexes, and cleanup markers reconcile after recovery with no visible partial release, orphaned authoritative object, duplicate version, or unfenced late write.
- [ ] The Data Worker is restored, named health checks converge, storage invariants and the post-gate state digest are recorded, and no Compute Worker fault is injected.
- [ ] The gate can be retried independently without re-running API/relay or Compute recovery, and failure preserves the exact Temporal, Data Worker, and storage state needed for diagnosis.
