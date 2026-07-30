# 17 — Harden ResearchRun lifecycle

**What to build:** Make ResearchRun creation and execution durable under
duplicate delivery, process interruption, transient retry, cancellation, and
operator-requested rerun.

**Blocked by:** 16 — Run research and publish the Result Bundle.

**Status:** ready-for-agent

- [ ] Repeated create delivery with one idempotency key resolves to one ResearchRun.
- [ ] The logical Run follows queued, running, and one terminal state while infrastructure Attempts retain their own timestamps and diagnostics.
- [ ] A transient failure may append another Attempt without changing frozen inputs or Run identity.
- [ ] Cancellation fences late worker publication and leaves the Run terminally cancelled.
- [ ] Worker restart recovers abandoned work without duplicate Result Bundles.
- [ ] A user-requested rerun creates a distinct ResearchRun and preserves the prior result or failure.
- [ ] UI state remains accurate after reload and exposes safe diagnostics for failed and cancelled Attempts.
