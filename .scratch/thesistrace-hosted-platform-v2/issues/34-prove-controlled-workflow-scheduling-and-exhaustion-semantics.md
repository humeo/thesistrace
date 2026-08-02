# 34 — Prove Controlled Workflow Scheduling and Exhaustion Semantics

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Prove scheduling, retry, cancellation, and exhaustion semantics
with deterministic controlled tests. Keep these fast contract checks separate
from live 2C4G capacity, long heartbeat redelivery, and operational Health.

**Blocked by:** 27 — Resume Only the Next Compatible Local Acceptance Gate.

**Status:** ready-for-agent

- [ ] Controlled tests prove the global four-slot dispatch contract, dedicated Data queue, P1/P3 forward progress, fairness bounds, and work-conserving behavior with stable virtual time and observable queue state.
- [ ] Heartbeat, retry, cancellation, and late-completion tests prove the domain and Temporal contracts without sleeping for the production heartbeat interval or requiring Docker maximum-load execution.
- [ ] Resource exhaustion is classified stably, receives at most the configured single retry, and leaves no partial authoritative result for research, publication, tracking, equivalence, or generation paths.
- [ ] Duplicate delivery and retry tests prove idempotent terminal transitions and preserve the original failure classification when retry is exhausted.
- [ ] The gate has a bounded fast runtime, emits per-contract evidence, and can run without creating or mutating a Hosted Core Session.
- [ ] Its result explicitly states that simulated slots and exhaustion prove workflow semantics only, not physical Worker capacity, co-resident service health, or production qualification.
