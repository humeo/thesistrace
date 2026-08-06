# 02 — Extract the one-shot database migration boundary

**What to build:** Make database migration an explicit operation that can
prepare an empty PostgreSQL database before API and Worker startup, while
keeping the existing Core runnable throughout the transition.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] One explicit backend command applies every owned Core migration to an
      empty PostgreSQL database and exits successfully.
- [ ] Repeating the migration command against the current Schema is safe and
      leaves the Schema unchanged.
- [ ] API and Worker startup verify that the required Schema is present but do
      not apply or mutate migrations themselves.
- [ ] API and Worker fail clearly before accepting work when the required
      Schema has not been migrated.
- [ ] The currently active local and test startup paths invoke migration before
      starting long-running processes, so this Ticket can land green before the
      Compose cutover.
- [ ] Concurrent long-running process startup no longer creates competing
      migration attempts.
- [ ] Tests cover clean migration, repeated migration, missing-Schema startup,
      and ordinary startup without Schema mutation through public commands or
      process boundaries.
