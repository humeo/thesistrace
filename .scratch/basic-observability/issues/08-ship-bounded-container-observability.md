# 08 — Ship bounded container observability

**What to build:** Deliver the complete basic observability capability through
the final Production Image and local Compose topology. Operators can access
bounded container logs, run both PostgreSQL-only diagnostics, distinguish
liveness from readiness, and trust that release evidence checks dependency
failure, recovery, and secret leakage.

**Blocked by:** 03 — Trace the DailyTrack lifecycle end to end; 04 — Trace Data Refresh phases safely; 06 — Diagnose one DailyTrack from PostgreSQL only; 07 — Report Core dependency readiness safely

**Status:** ready-for-agent

- [ ] Every Compose-managed service uses Docker `json-file` logging with `max-size` set to `10m` and `max-file` set to `3`.
- [ ] No Core process creates or rotates an application log file, and no repository log directory is introduced.
- [ ] The existing development log workflow shows current API, Research Worker, Tracking Worker, Data Operator, PostgreSQL, and RustFS container output.
- [ ] Container stop preserves Docker-managed history, while rotation, container recreation or deletion, development reset, and erase are documented as capable of removing it.
- [ ] Core architecture and operator documentation describe the implemented event envelope, level policy, correlation identities, diagnostic commands, liveness/readiness distinction, log access, bounded retention, and Product State authority without claiming dashboards, alerts, or permanent storage.
- [ ] The ordinary local test command executes every new fast formatter, HTTP, diagnostic, and architecture contract test; no new fast entrypoint suite remains outside that gate.
- [ ] Production Image smoke proves the packaged ResearchRun and DailyTrack diagnostic subcommands, successful liveness and readiness, one API completion event, ResearchRun lifecycle events, DailyTrack lifecycle events, and Data Refresh phase events.
- [ ] Production Image smoke fails and recovers PostgreSQL, RustFS, and the mounted Dataset Store at their real boundaries and retains sufficient bounded diagnostics when a condition times out.
- [ ] Secret canaries are absent from collected stdout, stderr, readiness responses, diagnostic snapshots, and failure artifacts in the final image.
- [ ] Child protocol stdout, Data Operator result stdout, and diagnostic snapshot stdout remain independently machine-readable in the final image.
- [ ] A repository-wide check confirms no obsolete first-party operational `print` path, dual event schema, compatibility formatter, fallback sink, telemetry state table, or log-based lifecycle decision remains.
- [ ] ADR-0217 remains indexed and implementation documentation agrees that PostgreSQL Product State is authoritative and telemetry is disposable diagnostic evidence.
- [ ] Focused tests, the ordinary local gate, real integration coverage, and Production Image Smoke all pass from a clean isolated environment.
- [ ] No Browser E2E or long-history performance benchmark is added because the capability has no Browser or calculation surface.

## Comments

- Parent: Basic Operational Observability.
