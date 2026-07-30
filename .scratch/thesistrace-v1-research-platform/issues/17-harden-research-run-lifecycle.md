# 17 — Harden ResearchRun lifecycle

**What to build:** Make ResearchRun creation and execution durable under
duplicate delivery, process interruption, transient retry, cancellation, and
operator-requested rerun.

**Blocked by:** 16 — Run research and publish the Result Bundle.

**Status:** resolved

- [x] Repeated create delivery with one idempotency key resolves to one ResearchRun.
- [x] The logical Run follows queued, running, and one terminal state while infrastructure Attempts retain their own timestamps and diagnostics.
- [x] A transient failure may append another Attempt without changing frozen inputs or Run identity.
- [x] Cancellation fences late worker publication and leaves the Run terminally cancelled.
- [x] Worker restart recovers abandoned work without duplicate Result Bundles.
- [x] A user-requested rerun creates a distinct ResearchRun and preserves the prior result or failure.
- [x] UI state remains accurate after reload and exposes safe diagnostics for failed and cancelled Attempts.

## Comments

- Added durable Attempt records, transient retry, terminal failure and
  cancellation, abandoned-attempt recovery, idempotent creation, and explicit
  immutable reruns.
- Worker execution, API reload state, safe diagnostics, and late-publication
  cancellation fencing are covered by acceptance and real-browser tests.
