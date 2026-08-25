# 09 — Recover Strategy Sweeps through a private shared artifact

**What to build:** Let a later Strategy Sweep Attempt reuse its own previously
acknowledged Alpha-and-Factor prerequisite through one private immutable artifact,
then continue at the first incomplete Strategy without creating a public or
cross-Batch cache.

**Blocked by:** 05 — Execute Strategy Sweeps from one shared Alpha and Factor; 08 — Recover complete Factor tasks with bounded retry

**Status:** complete

## Implementation plan

1. Define the private Strategy artifact binding and persistence contract: one
   owning Batch, frozen Generation/research/numeric/semantic facts, immutable
   object checksum, shared-task acknowledgement, and bounded task Attempts.
2. Extend the supervised child protocol so it stages only Attempt-scoped shared
   bytes or consumes one supervisor-authorized artifact; keep PostgreSQL,
   RustFS, publication, acknowledgement, and public API authority in the
   supervisor.
3. Publish and acknowledge the validated shared prerequisite atomically, then
   recover expired Strategy Attempts from the first incomplete whole Strategy,
   applying three-attempt limits independently to shared and Strategy tasks.
4. Release the private reference after every dependant is terminal and connect
   orphan Attempt files and unreferenced publication objects to existing
   authority-checked garbage collection.
5. Add real PostgreSQL/RustFS/process acceptance for reuse, rejection,
   restart, bounded retry, cleanup, and self-contained Results; run focused and
   full gates, resolve independent Standards/Spec review findings, and commit
   the ticket separately.

- [x] A complete Strategy Sweep Alpha-and-Factor outcome may be recorded as one private immutable artifact scoped to exactly one Research Batch.
- [x] The artifact binding includes the canonical Alpha, frozen Research scope, Data Generation, Numeric Execution Contract, field bindings, semantic versions, and owning Batch identity.
- [x] The execution child writes only Attempt-scoped files and cannot record, publish, acknowledge, or expose the artifact directly.
- [x] Before acknowledgement, the supervisor verifies canonical binding, expected object structure, integrity checksum, current fence, and active ownership.
- [x] Artifact reference recording and shared-task acknowledgement are atomic, so recorded recovery truth can never point at unvalidated or unowned bytes.
- [x] Unrecorded or partially staged files never become recovery input and cannot satisfy the shared prerequisite.
- [x] A new Attempt with a valid acknowledged artifact skips Alpha-and-Factor calculation and resumes at the first incomplete Strategy item.
- [x] Completed Strategy tasks are never recomputed, and an interrupted incomplete Strategy restarts as one complete Strategy task under the bounded retry policy.
- [x] Corrupt bytes, binding mismatch, stale fence, obsolete calculation contract, missing object, and attempted cross-Batch reuse are rejected before task acknowledgement or Result publication.
- [x] Shared-prerequisite retry exhaustion fails every dependent Strategy Run, while one Strategy retry exhaustion fails only that Run and later independent Strategy items continue.
- [x] Every successful child Result remains self-contained with the shared Factor Summary and its own Strategy outcome and provenance; clients never need artifact access.
- [x] The artifact has no public API, user-visible identity, permanent Alpha-store semantics, cross-Batch lookup, or use outside its owning Sweep.
- [x] After all dependent Strategies are terminal and no Attempt is active, the private reference is released transactionally and newly unreferenced bytes enter durable Publication garbage collection.
- [x] Garbage-collection failure remains retryable and cannot change Batch, Run, or Result Product State.
- [x] Collection and aged Attempt-file cleanup recheck authority and references under the Publication mutation boundary, including a race with a newly established reference.
- [x] Real PostgreSQL and RustFS acceptance covers valid same-Batch reuse, every invalid-artifact case, Worker restart, publication retry, orphan cutoff, reference release, and eventual object deletion.

## Comments

- Parent: Research Batch Worker.
- The artifact is recovery state only; it is not a Result and never becomes a general computation cache.
- Implementation: a Strategy Sweep child emits one bounded binary Attempt artifact; only the supervisor validates its exact Batch/Alpha/scope/Generation/numeric/field/semantic binding, records the private Publication reference, and acknowledges the shared task in one transaction. Recovery materializes only that acknowledged artifact, skips shared calculation, and resumes the first incomplete complete Strategy task.
- Recovery and cleanup: shared and per-Strategy task retries are independently bounded at three; invalid artifacts are permanent failures; terminal Sweeps transactionally release the private reference into the durable Publication deletion queue. Orphan uploads and aged Attempt files recheck references and authority under the Publication mutation lock.
- Verification: Ruff, diff whitespace, and shell syntax passed; final fast suite passed `569` tests. Focused final-review tests passed `6` real PostgreSQL/RustFS cases. Full isolated integration run `20260824t081618z-63353-d4916c22` passed `235` main tests plus ordinary PostgreSQL restart, Factor RustFS restart, Strategy RustFS restart, Factor PostgreSQL restart, and Strategy PostgreSQL artifact-reuse restart phases (`1 passed` each), then removed its containers, network, and volumes.
- Independent Standards re-review: PASS (`P0/P1/P2 = 0/0/0`) after closing fail-open NoSuchBucket handling, obsolete paths, duplicated recovery transactions, misleading binary/Factor names, and diagnostics.
- Independent Spec re-review: PASS (`P0/P1/P2 = 0/0/0`) after fixing aggregate terminal state, current semantic-contract enforcement, permanent artifact-integrity failure, and internally consistent invalid-artifact coverage.
