---
status: accepted
---

# Recompute failed Tracking Advances from the authoritative Head

Tracking Head is the sole recovery truth for DailyTrack. Advance creation uses
the then-current Data Generation and Tracking Worker Capacity to freeze the
exact contiguous oldest Target. The planner selects the largest count from 1
through 64 that fits the 75-percent execution-memory budget and is estimated to
run within 30 seconds. As with Research Chunk planning, 30 seconds is a sizing
target rather than a rejection limit: when one complete session fits memory but
exceeds the time target, the Advance selects one; when one session cannot fit,
the system still creates a blocked Advance with that oldest one-session Target
but creates no Attempt. Explicit Retry reevaluates whether the same frozen
Target now fits; it never expands or shrinks that Target.

Every Attempt retains that same Target. It resolves and pins the current Data
Generation once and uses that Generation for the complete Attempt. The
Generation must contain the frozen predecessor and exact ordered Target; a
calendar mismatch is a permanent data-integrity failure rather than permission
to expand, shrink, or rewrite the Advance. Dataset Head growth is handled by a
later Advance after this one succeeds.

The Attempt publishes one new immutable Tracking Checkpoint and moves the Head
only after every selected target session succeeds. Failure, recovered Worker or
supervisor loss, or ADR-0210-confirmed cancellation discards all prepared
output, releases the Attempt-scoped Generation Pin, leaves the Tracking Head
unchanged, and creates no private cross-Attempt Execution Checkpoint. Working
Cache remains disposable and cannot preserve uncommitted Attempt state.

A later Attempt under the persistent Advance resolves the then-current Data
Generation and recomputes the frozen Target from the unchanged Tracking Head.
This may produce different unpublished observations when Canonical Data values
have changed, but it never rewrites published tracking history, changes target
coordinates, or mixes two Generations inside one successful Tracking
Checkpoint.

Only unexpected Worker loss or transient PostgreSQL, RustFS, network, timeout,
or Publication unavailability is automatically retryable. One Tracking Attempt
Cycle contains the initial Attempt plus at most two automatic Attempts. The
second Attempt becomes eligible after 5 seconds and the third after 30 seconds;
each rejoins the fair Tracking queue rather than monopolizing a Worker. Every
retry starts again from the unchanged Head and may select the then-current
Generation.

A Canonical Data, calculation, domain-invariant, integrity, equivalence, or
accepted-capacity failure blocks the Track immediately; repeating the same
deterministic failure cannot improve it. Exhausting a transient Cycle also
blocks. Only explicit user Retry may reactivate the same Advance: it first
reevaluates the frozen Target against current Tracking Worker Capacity, remains
blocked without a Cycle or Attempt if that Target still cannot fit, and starts
a new three-Attempt Cycle only when execution becomes eligible. Dataset Head
movement, capacity change, and service restart never reactivate it
automatically. An explicit user Stop cancels without retry.
ADR-0210 makes that cancellation confirmed: the Track remains `stopping` until
the execution child exits, then releases the Pin and becomes `stopped`.

User-visible Tracking Progress reports the authoritative Head and lag, the
frozen current Target, the current Attempt position within its Cycle, retry
waiting state, and transient phase and current session. Transient liveness never
marks a session durably complete. Only successful atomic publication moves the
Head and reduces authoritative lag.

ResearchRun deliberately retains ADR-0195's private Chunk checkpoints because a
long historical Run is expensive. DailyTrack deliberately recomputes because
its normal incremental range is cheap; avoiding cross-Attempt Generation
binding, private-checkpoint compatibility, and blocked-Advance pin retention is
more valuable than recovering partial unpublished work. The 64-session Advance
cap also bounds catch-up after long downtime so this trade-off remains valid.
