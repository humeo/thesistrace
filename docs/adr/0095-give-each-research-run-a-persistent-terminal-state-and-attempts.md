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
explicit browser-local `Use as Draft` followed by ordinary Run. ADR-0190
replaces per-Attempt current-Generation selection with one Data Generation
frozen at ResearchRun admission and reused by every Attempt. The persistent
state machine, Attempt identity, bounded retry, and idempotent admission
decisions above remain accepted. ADR-0195 defines infrastructure retry as
validated continuation from a private ResearchRun-owned execution checkpoint
rather than unconditional full recomputation. ADR-0198 replaces the direct
`running -> cancelled` ResearchRun transition with cooperative
`running -> cancelling -> cancelled` termination. ADR-0209 supersedes
Tracking's immediate block after every failed Attempt: transient infrastructure
failure receives one Tracking Attempt Cycle containing an initial Attempt plus
at most two automatic Attempts, while permanent data, calculation, domain, or
capacity failure blocks immediately. Each Attempt recomputes from the unchanged
Tracking Head; the persistent Advance keeps no private execution checkpoint.
ADR-0209 also replaces the cancelled-Attempt clause: explicit Stop cancels the
active Attempt and stops the DailyTrack without making the Advance retryable.
Retry waiting belongs to the persistent Advance and Tracking Attempt Cycle; a
Tracking Advance Attempt starts in `running` only when a Worker claims it and
never has a queued state.
ADR-0210 requires confirmed execution-child exit before the Generation Pin is
released and the DailyTrack becomes terminal `stopped`; the stopped Track's
Advance becomes terminal `cancelled` rather than remaining blocked or
retryable.
