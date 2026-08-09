# 11 — Recover and fence failed or concurrent Refresh work

**What to build:** Make private Data Refresh safe under duplicate delivery,
concurrent Workers, bounded retry, process loss, and crashes at every commit
boundary while preserving one complete readable Dataset Head.

**Blocked by:** 10 — Refresh current data through a 20-session overlap merge.

**Status:** complete

- [x] Repeating the same idempotency key returns the same operation; conflicting reuse is rejected and cannot create a second executable Refresh.
- [x] Concurrent Workers can give publication ownership to only one Attempt, and at most one authoritative Head transition completes for that operation.
- [x] A lost Worker is fenced and recovered under the existing bounded retry policy; retry exhaustion reaches a sanitized terminal failure instead of remaining stuck as running.
- [x] Injected failure during collection, merge, derived recomputation, validation, Generation write, Head compare-and-swap, or PostgreSQL completion leaves the prior Head completely readable and leaves `last_refresh_at` unchanged.
- [x] A crash after atomic Head movement but before PostgreSQL operation completion is reconciled on restart to the same operation and Head without constructing a duplicate Generation.
- [x] A stale or late Worker cannot overwrite a newer Head, successful operation, retry outcome, or terminal failure.
- [x] Retryable and terminal failures have stable sanitized classifications in private inspection and production logs; source payloads, secrets, object locations, and raw exception details do not enter public responses.
- [x] Recovery acceptance uses real PostgreSQL and a mounted store, deterministic failure barriers, and timeout-bounded condition polling rather than fixed sleeps or private call-count assertions.
