# 08 — Ship bounded container observability

**What to build:** Deliver the complete basic observability capability through
the final Production Image and local Compose topology. Operators can access
bounded container logs, run both PostgreSQL-only diagnostics, distinguish
liveness from readiness, and trust that release evidence checks dependency
failure, recovery, and secret leakage.

**Blocked by:** 03 — Trace the DailyTrack lifecycle end to end; 04 — Trace Data Refresh phases safely; 06 — Diagnose one DailyTrack from PostgreSQL only; 07 — Report Core dependency readiness safely

**Status:** complete

- [x] Every Compose-managed service uses Docker `json-file` logging with `max-size` set to `10m` and `max-file` set to `3`.
- [x] No Core process creates or rotates an application log file, and no repository log directory is introduced.
- [x] The existing development log workflow shows current API, Research Worker, Tracking Worker, Data Operator, PostgreSQL, and RustFS container output.
- [x] Container stop preserves Docker-managed history, while rotation, container recreation or deletion, development reset, and erase are documented as capable of removing it.
- [x] Core architecture and operator documentation describe the implemented event envelope, level policy, correlation identities, diagnostic commands, liveness/readiness distinction, log access, bounded retention, and Product State authority without claiming dashboards, alerts, or permanent storage.
- [x] The ordinary local test command executes every new fast formatter, HTTP, diagnostic, and architecture contract test; no new fast entrypoint suite remains outside that gate.
- [x] Production Image smoke proves the packaged ResearchRun and DailyTrack diagnostic subcommands, successful liveness and readiness, one API completion event, ResearchRun lifecycle events, DailyTrack lifecycle events, and Data Refresh phase events.
- [x] Production Image smoke fails and recovers PostgreSQL, RustFS, and the mounted Dataset Store at their real boundaries and retains sufficient bounded diagnostics when a condition times out.
- [x] Secret canaries are absent from collected stdout, stderr, readiness responses, diagnostic snapshots, and failure artifacts in the final image.
- [x] Child protocol stdout, Data Operator result stdout, and diagnostic snapshot stdout remain independently machine-readable in the final image.
- [x] A repository-wide check confirms no obsolete first-party operational `print` path, dual event schema, compatibility formatter, fallback sink, telemetry state table, or log-based lifecycle decision remains.
- [x] ADR-0217 remains indexed and implementation documentation agrees that PostgreSQL Product State is authoritative and telemetry is disposable diagnostic evidence.
- [x] Focused tests, the ordinary local gate, real integration coverage, and Production Image Smoke all pass from a clean isolated environment.
- [x] No Browser E2E or long-history performance benchmark is added because the capability has no Browser or calculation surface.

## Comments

- Parent: Basic Operational Observability.
- Implementation: all seven canonical Compose services use bounded Docker
  `json-file` logs (`10m` x `3`), Development suppresses duplicate Uvicorn
  access output, remaining first-party operational paths emit through the safe
  event envelope, and the release runner validates packaged diagnostics,
  health, lifecycle events, dependency outages, machine-readable stdout, and
  credential/request canaries without adding a log directory or telemetry
  Product State.
- Review: independent Standards and Spec reviews found that failure artifacts
  were not scanned when an earlier smoke phase failed and that a Tracking
  Worker cache-cleanup warning was attributed to `core_api`. The failure path
  now scans newly captured evidence and records its result, while the Worker
  injects a fail-open `tracking_worker`/`tracking` sink. Both independent
  re-reviews were clean.
- Verification: Ruff and diff-check passed; focused Worker, failure-evidence,
  lifecycle, and architecture lanes passed (61 plus one boundary test); the
  ordinary gate passed 555 backend tests and 56 Web shell tests with Web
  typecheck; a fresh isolated integration run passed 213 tests plus the
  separate PostgreSQL restart test and cleaned its project; Production Image
  Smoke run `20260823t233013z-25851-b42e1971` completed every phase and cleanup
  with status 0. No Browser E2E or long-history benchmark was added.

## Plan

1. Apply one Docker `json-file` logging policy (`10m` × `3`) to every service
   in the canonical Compose topology, keep the API restart probe on liveness,
   disable duplicate Uvicorn access output in Development, and add fast
   architecture contracts for bounded retention and the absence of
   application-owned log files or directories.
2. Hard-cut the remaining first-party ad hoc operational output to the
   canonical safe event boundary while preserving child protocol stdout, Data
   Operator result stdout, diagnostic stdout, and their existing exit
   contracts; add a repository-wide source contract against obsolete print,
   alternate logger, compatibility, fallback, and telemetry-state paths.
3. Extend Production Image Smoke with packaged ResearchRun/DailyTrack
   diagnostics, healthy liveness/readiness, one API completion event, lifecycle
   and Data Refresh phase events, and real fail/recover checks for PostgreSQL,
   RustFS, and the mounted Dataset root using condition polling and bounded
   failure evidence.
4. Inject real credential and request canaries into the isolated image topology,
   collect only safe container state/log evidence, and scan stdout, stderr,
   readiness, diagnostic snapshots, operational logs, and timeout artifacts
   without corrupting the child, operator, or diagnostic machine-readable
   stdout contracts.
5. Document the implemented event envelope, level/correlation policy,
   PostgreSQL Product State authority, diagnostic commands, health semantics,
   Docker log access/rotation/loss boundaries, and explicit lack of dashboards,
   alerts, or permanent retention; include every fast entrypoint test in the
   ordinary local gate.
6. Run focused architecture and output-boundary lanes, the ordinary local gate,
   real integration coverage, and final Production Image Smoke; complete
   independent Standards and Spec reviews, fix and re-review, complete this
   tracker, and create one Ticket 08 commit.
