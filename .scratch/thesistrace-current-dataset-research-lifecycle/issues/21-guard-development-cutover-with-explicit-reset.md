# 21 — Guard development cutover with explicit Reset

**What to build:** Provide a narrowly scoped, deployment-private Development
Reset that can remove unsupported pre-production Release-bound state only with
an explicit environment guard and confirmation, before the final schema
contract activates its legacy-state refusal.

**Blocked by:** 08 — Bootstrap a Head through the private Data Operator.

**Status:** ready-for-agent

- [ ] Development Reset exists only on the private operator surface and is absent from ordinary HTTP and Web interfaces.
- [ ] Reset requires an explicitly identified development environment and an affirmative confirmation bound to that same environment; missing or mismatched values leave every store unchanged.
- [ ] A production environment refuses Reset even with confirmation and preserves PostgreSQL, RustFS, and mounted filesystem state.
- [ ] Successful Reset targets only legacy Dataset Release, ResearchRun, Attempt, Result, and DailyTrack execution state, their owned RustFS references, and the explicitly configured development data mount.
- [ ] Research Definition drafts, unrelated PostgreSQL rows, every path outside the configured mount, and unrelated or still-shared RustFS objects are preserved; RustFS deletion is reference-aware and cannot remove an object retained by another manifest.
- [ ] Before mutation, Reset resolves and validates exact PostgreSQL, RustFS, and filesystem targets; an empty target, filesystem root, workspace or parent directory, overbroad object namespace, or symbolic-link escape is rejected with zero modification.
- [ ] Interruption at each storage boundary leaves a bounded diagnostic and a safely retryable Reset that cannot expand its target set on retry.
- [ ] Reset remains callable without ordinary Runtime readiness and does not itself Bootstrap, Refresh, or contact Tushare; activation of startup and migration refusal remains in the final Release-contract ticket.
