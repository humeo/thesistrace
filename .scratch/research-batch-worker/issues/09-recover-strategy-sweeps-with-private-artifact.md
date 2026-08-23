# 09 — Recover Strategy Sweeps through a private shared artifact

**What to build:** Let a later Strategy Sweep Attempt reuse its own previously
acknowledged Alpha-and-Factor prerequisite through one private immutable artifact,
then continue at the first incomplete Strategy without creating a public or
cross-Batch cache.

**Blocked by:** 05 — Execute Strategy Sweeps from one shared Alpha and Factor; 08 — Recover complete Factor tasks with bounded retry

**Status:** ready-for-agent

- [ ] A complete Strategy Sweep Alpha-and-Factor outcome may be recorded as one private immutable artifact scoped to exactly one Research Batch.
- [ ] The artifact binding includes the canonical Alpha, frozen Research scope, Data Generation, Numeric Execution Contract, field bindings, semantic versions, and owning Batch identity.
- [ ] The execution child writes only Attempt-scoped files and cannot record, publish, acknowledge, or expose the artifact directly.
- [ ] Before acknowledgement, the supervisor verifies canonical binding, expected object structure, integrity checksum, current fence, and active ownership.
- [ ] Artifact reference recording and shared-task acknowledgement are atomic, so recorded recovery truth can never point at unvalidated or unowned bytes.
- [ ] Unrecorded or partially staged files never become recovery input and cannot satisfy the shared prerequisite.
- [ ] A new Attempt with a valid acknowledged artifact skips Alpha-and-Factor calculation and resumes at the first incomplete Strategy item.
- [ ] Completed Strategy tasks are never recomputed, and an interrupted incomplete Strategy restarts as one complete Strategy task under the bounded retry policy.
- [ ] Corrupt bytes, binding mismatch, stale fence, obsolete calculation contract, missing object, and attempted cross-Batch reuse are rejected before task acknowledgement or Result publication.
- [ ] Shared-prerequisite retry exhaustion fails every dependent Strategy Run, while one Strategy retry exhaustion fails only that Run and later independent Strategy items continue.
- [ ] Every successful child Result remains self-contained with the shared Factor Summary and its own Strategy outcome and provenance; clients never need artifact access.
- [ ] The artifact has no public API, user-visible identity, permanent Alpha-store semantics, cross-Batch lookup, or use outside its owning Sweep.
- [ ] After all dependent Strategies are terminal and no Attempt is active, the private reference is released transactionally and newly unreferenced bytes enter durable Publication garbage collection.
- [ ] Garbage-collection failure remains retryable and cannot change Batch, Run, or Result Product State.
- [ ] Collection and aged Attempt-file cleanup recheck authority and references under the Publication mutation boundary, including a race with a newly established reference.
- [ ] Real PostgreSQL and RustFS acceptance covers valid same-Batch reuse, every invalid-artifact case, Worker restart, publication retry, orphan cutoff, reference release, and eventual object deletion.

## Comments

- Parent: Research Batch Worker.
- The artifact is recovery state only; it is not a Result and never becomes a general computation cache.
