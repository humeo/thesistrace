# 06 — Diagnose one DailyTrack from PostgreSQL only

**What to build:** Extend the private diagnostic command so an operator can
explain one DailyTrack from its authoritative Head through the active or latest
Tracking Advance, Attempts, retry Cycle, blocked state, and Tracking Checkpoint
without opening non-PostgreSQL dependencies.

**Blocked by:** 05 — Diagnose one ResearchRun from PostgreSQL only

**Status:** complete

- [x] The installed `thesistrace-core-diagnose daily-track TRACK_ID` command uses the established PostgreSQL-only runtime and output contract.
- [x] The DailyTrack module owns its diagnostic query and read model; the command composes it without cross-domain SQL.
- [x] The snapshot contains PostgreSQL-derived `diagnosed_at`, Track identity, DailyTrack State, authoritative Tracking Head, Tracking Progress, recovery state, and publication state.
- [x] The active or latest Tracking Advance includes its identity, frozen Target summary, Cycle position, retry eligibility and timing, and blocked state when those facts exist.
- [x] Every relevant Tracking Advance Attempt appears in chronological order with identity, ordinal, status, phase, start and finish time, heartbeat, lease expiry, retry timing, and sanitized `failure_code`.
- [x] Attempt `lease_state` is derived only from PostgreSQL current time and persisted `lease_expires_at`; logs are never queried or interpreted.
- [x] Tracking Checkpoint presence is explicit without returning Strategy state, Checkpoint payload, manifest, checksum, object key, or physical path.
- [x] Formula, Hypothesis, command payload, raw stack, exception message, SQL, DSN, credential, endpoint, object key, and physical path are absent from stdout and stderr.
- [x] Exit codes retain the command-wide contract: 0 for a produced snapshot including blocked, failed, stopped, or terminal Tracks; 2 for usage; 3 for not found; and 4 for PostgreSQL or query failure.
- [x] Real PostgreSQL tests cover idle, advancing, retry-waiting, blocked, failed, stopping, stopped, published, current-lease, expired-lease, zero-Attempt, and multiple-Attempt states.
- [x] Tests prove the frozen Target, authoritative Head, and in-flight Progress cannot be confused and that ordering and explicit null behavior are stable.
- [x] An integration test makes RustFS and the mounted Dataset Store unavailable and proves DailyTrack diagnosis still succeeds without attempting either dependency.
- [x] The ResearchRun diagnostic subcommand and its JSON and exit-code contracts remain unchanged.

## Comments

- Parent: Basic Operational Observability.
- Implementation: added a DailyTrack-owned repeatable-read PostgreSQL snapshot
  that separates authoritative Head, frozen Advance Target, in-flight Progress,
  ordered Attempts, recovery, blocked state, and Checkpoint publication facts.
  The installed command extends the existing safe PostgreSQL-only adapter, and
  execution plus diagnostics share one allowlisted failure/retry policy.
- Review: initial independent reviews found that transient `current_session`
  was being counted as durable completion, unpublished `result_ready/staging`
  was still treated as complete, stable `UserStopped` and
  `NumericContractError` identities were missing, and lease tests used the
  process clock. All were fixed; final independent Standards and Spec
  re-reviews were clean.
- Verification: Ruff and diff-check passed; focused architecture lane 2 passed;
  fresh isolated real PostgreSQL DailyTrack lane 2 passed and the final combined
  DailyTrack/ResearchRun diagnostic regression lane 5 passed; complete backend
  fast lane 548 passed with 2 existing warnings; Web typecheck passed; Web shell
  lane 56 passed. All one-off PostgreSQL containers and temporary data
  directories were removed.

## Plan

1. Add a DailyTrack-owned repeatable-read PostgreSQL diagnostic projection for
   one Track, its authoritative Tracking Head, active-or-latest frozen Advance,
   committed Progress, ordered Attempts, recovery/blocked state, and Checkpoint
   publication presence without selecting private JSON or manifest columns.
2. Introduce one shared DailyTrack failure policy used by execution recovery and
   diagnostics so retry eligibility, attempt limits, and allowlisted failure
   codes cannot drift; derive lease state only from PostgreSQL observation time
   and persisted `lease_expires_at`.
3. Extend the existing safe `thesistrace-core-diagnose` adapter with
   `daily-track TRACK_ID`, preserving the ResearchRun JSON and exit contracts and
   constructing only `PostgresDatabase` plus the selected module reader.
4. Add real PostgreSQL state-matrix and installed-command coverage for idle,
   advancing, retry-waiting, blocked/failed, stopping, stopped, published,
   current/expired lease, zero/multiple Attempt, ordering, explicit nulls,
   Head/Target/Progress separation, secret canaries, and unavailable RustFS and
   Dataset paths.
5. Run focused architecture and real-PostgreSQL lanes, Ruff, the complete fast
   backend and Web gates; complete independent Standards and Spec reviews, fix
   and re-review, update this tracker, and create one Ticket 06 commit.
