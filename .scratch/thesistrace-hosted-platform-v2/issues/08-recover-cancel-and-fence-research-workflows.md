# 08 — Recover, cancel, and fence Research Workflows

**What to build:** Keep one ResearchRun authoritative across request crashes,
outbox interruption, Activity redelivery, cooperative cancellation, and
resource exhaustion without ever publishing a partial or late result.

**Blocked by:** 07 — Run one Research Workflow through Temporal.

**Status:** complete

- [x] Interrupting the API after its database commit or interrupting the outbox relay before or after Workflow start eventually executes the accepted ResearchRun without creating a second domain resource.
- [x] Activity retries and redelivery create Attempts under the existing ResearchRun and all external writes are idempotent.
- [x] User-requested rerun creates a new ResearchRun with the same frozen inputs, while an infrastructure retry preserves the original ResearchRun identity.
- [x] Cancelling queued or running work is cooperatively delivered to eligible Activities and final publication is fenced so a late Worker cannot publish after cancellation.
- [x] A resource-exhausted Activity executes automatically at most twice in total, then terminates with stable `RESOURCE_EXHAUSTED` classification rather than quota or research-validation failure.
- [x] The same at-most-one automatic resource-exhaustion retry and no-partial-publication policy is the shared Activity contract consumed by later Dataset Publication, Tracking Advance, Equivalence, and Generation rebuild Workflows; ThesisTrace introduces no parallel lease or retry scheduler.
- [x] Failed, cancelled, and repeatedly exhausted work publishes no partial Result Bundle and removes temporary or unreferenced staging objects.
- [x] User-visible failures are stable and sanitized, while operator diagnostics retain correlation without credentials, research payloads, or another Personal Workspace's details.

**Acceptance evidence:** Research execution now uses one shared heavy-Activity
retry contract with heartbeats and cooperative cancellation. Cancellation is
committed as a second command in the existing RLS-protected execution Outbox
and delivered to the stable Temporal Workflow identity. Focused tests passed
all `26` recovery,
cancellation, resource-exhaustion, result-fencing, and staging-cleanup
scenarios; the production PostgreSQL RLS contract passed both two-User
isolation scenarios. In the real Hosted Compose stack, queued and running
cancellation both reached terminal `cancelled` state without a Result Bundle.
Killing the only active Compute Worker during calculation preserved the
original ResearchRun, fenced Attempt 1 as `ACTIVITY_REDELIVERED`, and completed
Attempt 2 after Worker recovery. Re-sending cancellation to the completed
Workflow was idempotent. The complete Python suite passed `112` tests with `6`
environment-gated skips. A deterministic real-PostgreSQL race exercised both
publication-first and cancellation-first lock orderings; each left the Run,
Attempt, and Result Bundle reference in one consistent terminal state.
Per-Run publication guards and an fsynced per-Attempt install journal recover
staging after process death and resolve an uncertain database commit by
re-reading the authoritative manifest digest. Subprocess hard-crash tests
prove that uncommitted private manifests and staging are removed, committed
manifests survive, and recovery never deletes shared content-addressed
objects reused by another Run. Publication guards use a fixed 256-bucket lock
namespace, and finalization logs distinguish user cancellation, an already
committed result, and actual Activity delivery exhaustion.
