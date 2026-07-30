# 08 — Recover, cancel, and fence Research Workflows

**What to build:** Keep one ResearchRun authoritative across request crashes,
outbox interruption, Activity redelivery, cooperative cancellation, and
resource exhaustion without ever publishing a partial or late result.

**Blocked by:** 07 — Run one Research Workflow through Temporal.

**Status:** ready-for-agent

- [ ] Interrupting the API after its database commit or interrupting the outbox relay before or after Workflow start eventually executes the accepted ResearchRun without creating a second domain resource.
- [ ] Activity retries and redelivery create Attempts under the existing ResearchRun and all external writes are idempotent.
- [ ] User-requested rerun creates a new ResearchRun with the same frozen inputs, while an infrastructure retry preserves the original ResearchRun identity.
- [ ] Cancelling queued or running work is cooperatively delivered to eligible Activities and final publication is fenced so a late Worker cannot publish after cancellation.
- [ ] A resource-exhausted Activity executes automatically at most twice in total, then terminates with stable `RESOURCE_EXHAUSTED` classification rather than quota or research-validation failure.
- [ ] The same at-most-one automatic resource-exhaustion retry and no-partial-publication policy is the shared Activity contract consumed by later Dataset Publication, Tracking Advance, Equivalence, and Generation rebuild Workflows; ThesisTrace introduces no parallel lease or retry scheduler.
- [ ] Failed, cancelled, and repeatedly exhausted work publishes no partial Result Bundle and removes temporary or unreferenced staging objects.
- [ ] User-visible failures are stable and sanitized, while operator diagnostics retain correlation without credentials, research payloads, or another Personal Workspace's details.
