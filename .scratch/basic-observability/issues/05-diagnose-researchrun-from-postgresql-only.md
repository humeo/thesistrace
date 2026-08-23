# 05 — Diagnose one ResearchRun from PostgreSQL only

**What to build:** Give an operator one private command that explains a
ResearchRun from authoritative PostgreSQL Product State even when RustFS or the
mounted Dataset Store is unavailable. The output is a safe, stable JSON
snapshot suitable for inspection and scripting.

**Blocked by:** None — can start immediately

**Status:** complete

- [x] The installed `thesistrace-core-diagnose research-run RUN_ID` command opens PostgreSQL configuration without constructing RustFS, Publication, Dataset Store, Worker, or the complete Core runtime.
- [x] The ResearchRun module owns its diagnostic query and read model; the command remains a thin adapter and does not own cross-domain SQL.
- [x] Successful stdout is stable, indented JSON with sorted object keys, UTC RFC 3339 timestamps, explicit nulls, and explicit presence booleans.
- [x] The snapshot contains PostgreSQL-derived `diagnosed_at`, Run identity, Research Kind, ResearchRun State, current phase, committed ResearchRun Progress, recovery state, and publication state.
- [x] Every ResearchRun Attempt appears in chronological order with identity, ordinal, status, phase, start and finish time, heartbeat, lease expiry, retry timing, and sanitized `failure_code` when those facts exist.
- [x] Attempt `lease_state` is derived only from PostgreSQL current time and persisted `lease_expires_at`; log presence or recency is never consulted.
- [x] The snapshot reports private Checkpoint and Result Bundle presence without returning payloads, manifests, checksums, object keys, or storage paths.
- [x] Formula, Hypothesis, immutable command payload, raw stack, exception message, SQL, DSN, credential, endpoint, object key, and physical path are absent from stdout and stderr.
- [x] Exit code 0 means a valid snapshot was produced even for failed, cancelled, or otherwise terminal ResearchRuns; exit code 2 means invalid usage, 3 means not found, and 4 means PostgreSQL or query failure.
- [x] Invocation and dependency failures write a concise safe error to stderr and never mix telemetry or errors into successful stdout.
- [x] Real PostgreSQL tests cover queued, running, retrying, failed, cancelled, successful, unpublished, published, current-lease, expired-lease, zero-Attempt, and multiple-Attempt states with stable ordering and exit codes.
- [x] An integration test makes RustFS and the mounted Dataset Store unavailable and proves the command still returns the same ResearchRun snapshot without attempting either dependency.
- [x] The diagnostic command is included in the current console-script contract without restoring obsolete entrypoints or introducing a second runtime.

## Comments

- Parent: Basic Operational Observability.
- Implementation: added the installed private command, a ResearchRun-owned
  repeatable-read PostgreSQL snapshot, explicit Progress/Attempt/recovery and
  publication projections, and a shared ResearchRun failure policy used by both
  execution and diagnostics. The command never constructs the complete Runtime
  or any non-PostgreSQL dependency.
- Review: initial independent reviews found unsafe default argparse echo,
  non-allowlisted failure identities, stale Checkpoint phase precedence for the
  current Attempt, and duplicated retry policy. All were fixed; final independent
  Standards and Spec re-reviews were clean.
- Verification: Ruff and diff-check passed; focused architecture lane 3 passed;
  fresh isolated real PostgreSQL diagnostic lane 3 passed, including the
  installed command and hostile unavailable storage configuration; complete
  backend fast lane 548 passed with 2 existing warnings; Web typecheck passed;
  Web shell lane 56 passed. The one-off PostgreSQL container and temporary data
  directory were removed.

## Plan

1. Add a ResearchRun-owned PostgreSQL diagnostic read model that returns one
   consistent snapshot of Run, committed Progress, ordered Attempts, lease and
   retry recovery state, Checkpoint presence, and Result Bundle publication
   presence without reading private payload columns.
2. Derive lease state only from the database observation time, persisted Attempt
   status, and `lease_expires_at`; normalize only known-safe failure identities
   and render every optional diagnostic fact explicitly as JSON null or a
   presence boolean.
3. Add the thin installed `thesistrace-core-diagnose research-run RUN_ID`
   adapter. It opens only `PostgresDatabase`, writes one indented/sorted JSON
   snapshot to stdout, emits safe concise failures to stderr, and implements
   exit codes 2/3/4 without opening Runtime, RustFS, Publication, or Dataset.
4. Cover queued, active/current lease, expired lease, retry pending, failed,
   cancelled, successful, unpublished, published, zero-Attempt, multiple-Attempt,
   sanitized failure, stable ordering, timestamp/null shape, and all exit codes
   against real PostgreSQL; prove invalid RustFS and Dataset paths do not affect
   the public CLI snapshot.
5. Run focused architecture and real-PostgreSQL lanes, Ruff, complete fast
   backend and Web gates; complete independent Standards and Spec reviews, fix
   and re-review, update this tracker, and create one Ticket 05 commit.
