# 06 — Diagnose one DailyTrack from PostgreSQL only

**What to build:** Extend the private diagnostic command so an operator can
explain one DailyTrack from its authoritative Head through the active or latest
Tracking Advance, Attempts, retry Cycle, blocked state, and Tracking Checkpoint
without opening non-PostgreSQL dependencies.

**Blocked by:** 05 — Diagnose one ResearchRun from PostgreSQL only

**Status:** ready-for-agent

- [ ] The installed `thesistrace-core-diagnose daily-track TRACK_ID` command uses the established PostgreSQL-only runtime and output contract.
- [ ] The DailyTrack module owns its diagnostic query and read model; the command composes it without cross-domain SQL.
- [ ] The snapshot contains PostgreSQL-derived `diagnosed_at`, Track identity, DailyTrack State, authoritative Tracking Head, Tracking Progress, recovery state, and publication state.
- [ ] The active or latest Tracking Advance includes its identity, frozen Target summary, Cycle position, retry eligibility and timing, and blocked state when those facts exist.
- [ ] Every relevant Tracking Advance Attempt appears in chronological order with identity, ordinal, status, phase, start and finish time, heartbeat, lease expiry, retry timing, and sanitized `failure_code`.
- [ ] Attempt `lease_state` is derived only from PostgreSQL current time and persisted `lease_expires_at`; logs are never queried or interpreted.
- [ ] Tracking Checkpoint presence is explicit without returning Strategy state, Checkpoint payload, manifest, checksum, object key, or physical path.
- [ ] Formula, Hypothesis, command payload, raw stack, exception message, SQL, DSN, credential, endpoint, object key, and physical path are absent from stdout and stderr.
- [ ] Exit codes retain the command-wide contract: 0 for a produced snapshot including blocked, failed, stopped, or terminal Tracks; 2 for usage; 3 for not found; and 4 for PostgreSQL or query failure.
- [ ] Real PostgreSQL tests cover idle, advancing, retry-waiting, blocked, failed, stopping, stopped, published, current-lease, expired-lease, zero-Attempt, and multiple-Attempt states.
- [ ] Tests prove the frozen Target, authoritative Head, and in-flight Progress cannot be confused and that ordering and explicit null behavior are stable.
- [ ] An integration test makes RustFS and the mounted Dataset Store unavailable and proves DailyTrack diagnosis still succeeds without attempting either dependency.
- [ ] The ResearchRun diagnostic subcommand and its JSON and exit-code contracts remain unchanged.

## Comments

- Parent: Basic Operational Observability.
