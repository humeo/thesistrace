---
status: accepted
---

# Give each ResearchRun a persistent terminal state and attempts

Every ResearchRun has one persistent state transition:

```text
queued -> running -> succeeded | failed | cancelled
```

A retry of a transient infrastructure failure creates another execution
attempt under the same ResearchRun identity. It does not create another
user-visible run or change the frozen Research Definition and calculation
contracts. Each new Attempt selects and pins the then-current Data Generation.

A user-requested rerun always creates a new ResearchRun identity and preserves
the earlier run and its result or diagnostics. A cancelled run is terminal; a
later execution is likewise a new run. Creation accepts an idempotency key so
repeated delivery of the same create request resolves to the same ResearchRun
instead of starting duplicates.

Tracking Advance is not a ResearchRun or user rerun. Under ADR-0105, its
Attempts use the same execution terminal states, but a failed or cancelled
Attempt leaves the persistent Advance blocked and retryable. The Advance
identity is scoped to one DailyTrack and target Research Session progression and
becomes terminal only on success.

## Superseded clauses

ADR-0171 replaces the frozen Research Definition wording with immutable
ResearchRun input, and ADR-0182 replaces the user-requested rerun action with
explicit browser-local `Use as Draft` followed by ordinary Run. The persistent
state machine, Attempt retry, cancellation, and idempotent admission decisions
above remain accepted.
