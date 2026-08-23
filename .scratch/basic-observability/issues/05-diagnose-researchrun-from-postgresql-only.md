# 05 — Diagnose one ResearchRun from PostgreSQL only

**What to build:** Give an operator one private command that explains a
ResearchRun from authoritative PostgreSQL Product State even when RustFS or the
mounted Dataset Store is unavailable. The output is a safe, stable JSON
snapshot suitable for inspection and scripting.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] The installed `thesistrace-core-diagnose research-run RUN_ID` command opens PostgreSQL configuration without constructing RustFS, Publication, Dataset Store, Worker, or the complete Core runtime.
- [ ] The ResearchRun module owns its diagnostic query and read model; the command remains a thin adapter and does not own cross-domain SQL.
- [ ] Successful stdout is stable, indented JSON with sorted object keys, UTC RFC 3339 timestamps, explicit nulls, and explicit presence booleans.
- [ ] The snapshot contains PostgreSQL-derived `diagnosed_at`, Run identity, Research Kind, ResearchRun State, current phase, committed ResearchRun Progress, recovery state, and publication state.
- [ ] Every ResearchRun Attempt appears in chronological order with identity, ordinal, status, phase, start and finish time, heartbeat, lease expiry, retry timing, and sanitized `failure_code` when those facts exist.
- [ ] Attempt `lease_state` is derived only from PostgreSQL current time and persisted `lease_expires_at`; log presence or recency is never consulted.
- [ ] The snapshot reports private Checkpoint and Result Bundle presence without returning payloads, manifests, checksums, object keys, or storage paths.
- [ ] Formula, Hypothesis, immutable command payload, raw stack, exception message, SQL, DSN, credential, endpoint, object key, and physical path are absent from stdout and stderr.
- [ ] Exit code 0 means a valid snapshot was produced even for failed, cancelled, or otherwise terminal ResearchRuns; exit code 2 means invalid usage, 3 means not found, and 4 means PostgreSQL or query failure.
- [ ] Invocation and dependency failures write a concise safe error to stderr and never mix telemetry or errors into successful stdout.
- [ ] Real PostgreSQL tests cover queued, running, retrying, failed, cancelled, successful, unpublished, published, current-lease, expired-lease, zero-Attempt, and multiple-Attempt states with stable ordering and exit codes.
- [ ] An integration test makes RustFS and the mounted Dataset Store unavailable and proves the command still returns the same ResearchRun snapshot without attempting either dependency.
- [ ] The diagnostic command is included in the current console-script contract without restoring obsolete entrypoints or introducing a second runtime.

## Comments

- Parent: Basic Operational Observability.
