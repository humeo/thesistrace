# 17 — Delete terminal resources through Tombstones

**What to build:** Let a User irreversibly delete one complete terminal private
resource, make it unreadable immediately, and reconcile physical cleanup and
quota release through a permanent minimal Resource Tombstone.

**Blocked by:** 11 — Activate and stop a quota-bound DailyTrack; 16 — Enforce private storage and disk admission; `thesistrace-bounded-research-storage/09 — Reconcile Working Cache deletion after DailyTrack stop`.

**Status:** ready-for-agent

- [ ] Web and API permit deletion only for terminal ResearchRuns and stopped DailyTracks in the caller's Personal Workspace.
- [ ] A ResearchRun referenced by a retained DailyTrack and any nonterminal resource are rejected without mutating their lifecycle or artifacts.
- [ ] One atomic control transaction removes live product references, makes the resource immediately unreadable, and creates a permanent minimal Tombstone with identity, authoritative manifest hash, actor, and deletion time.
- [ ] Object cleanup is reference-aware and idempotent, so shared bytes remain while any live resource still references them.
- [ ] Private-storage quota is released only after the physical bytes and stopped Track Working Cache namespace are actually removed.
- [ ] A crash after the deletion or stop commit but before cleanup is recovered by durable cleanup work and scheduled or startup reconciliation.
- [ ] Another Personal Workspace cannot delete or inspect the resource or its Tombstone, and ordinary Users receive no restore or soft-delete surface.
