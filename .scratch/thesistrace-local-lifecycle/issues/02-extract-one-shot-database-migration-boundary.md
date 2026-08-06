# 02 — Extract the one-shot database migration boundary

**What to build:** Make database migration an explicit operation that can
prepare an empty PostgreSQL database before API and Worker startup, while
keeping the existing Core runnable throughout the transition.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] One explicit backend command applies every owned Core migration to an
      empty PostgreSQL database and exits successfully.
- [x] Repeating the migration command against the current Schema is safe and
      leaves the Schema unchanged.
- [x] API and Worker startup verify that the required Schema is present but do
      not apply or mutate migrations themselves.
- [x] API and Worker fail clearly before accepting work when the required
      Schema has not been migrated.
- [x] The currently active local and test startup paths invoke migration before
      starting long-running processes, so this Ticket can land green before the
      Compose cutover.
- [x] Concurrent long-running process startup no longer creates competing
      migration attempts.
- [x] Tests cover clean migration, repeated migration, missing-Schema startup,
      and ordinary startup without Schema mutation through public commands or
      process boundaries.

## Comments

- Implemented in `038df14` and review fixes in `b2ef040`.
- Verified Ruff and focused architecture tests, the real `thesistrace-migrate`
  process boundary against PostgreSQL/RustFS, missing-Schema API/Worker failure,
  repeated migration, and adjacent ordered recovery tests.
- Two review rounds used the fixed point `ed323ed`; final Standards and Spec
  reviews reported no material findings.
