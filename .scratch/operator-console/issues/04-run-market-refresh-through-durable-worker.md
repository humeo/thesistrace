# 04 — Run Market Refresh through the durable Data Operator Worker

**What to build:** Let the Operator submit a Market Refresh from the Console and
observe one durable operation progress to publication or no change through the
same always-running Worker and application service used by the private CLI.

**Blocked by:** 02 — Secure Invitation mutations with Operator Proof.

**Status:** ready-for-agent

- [ ] The Market form accepts the same explicit timezone-aware `as-of` value and
  backend validation as the private CLI; the server never silently selects a
  target date.
- [ ] The form suggests a kind-and-time-based idempotency key, permits editing,
  and displays the exact accepted key in subsequent operation state.
- [ ] The Core mutation consumes an Operator Proof through bounded internal Auth
  verification; Core and the Worker never receive the Operator's password.
- [ ] Successful submission durably creates a Market Data Refresh Operation in
  `accepted` state and returns without waiting for collection or publication;
  persistence failure never reports acceptance.
- [ ] One always-running, single-slot Data Operator Worker claims and executes the
  Market operation and records a safe terminal publication, no-change, or failure
  outcome.
- [ ] The Console shows enough immediate state to distinguish accepted, running,
  published, no change, and failed without exposing upstream bodies, secrets,
  manifests, or object paths.
- [ ] Reusing an idempotency key with the same canonical request returns the same
  operation; reusing it for different input is rejected without duplicate work.
- [ ] Console and CLI submissions use the same durable operation and validation
  services, and the obsolete manually invoked Market worker path is removed as a
  hard cut rather than kept as a fallback.
- [ ] Real-PostgreSQL and deterministic-replay integration tests cover submission,
  idempotency, claim, execution, publication, no change, failure, and proof
  rejection.
- [ ] A real browser test proves password-confirmed submission and asynchronous
  status progression through the same-origin application.
