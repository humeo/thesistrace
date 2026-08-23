# Basic Operational Observability

**Status:** complete

## Problem Statement

ThesisTrace Core has durable Product State for ResearchRun, DailyTrack, and Data
Refresh, but it does not yet provide one dependable operational view of that
state. The API, Workers, execution children, and Data Operator currently emit a
mixture of standard logging, event dictionaries, and direct printed JSON.
Fields, levels, correlation identities, failure treatment, and secret handling
therefore vary by process.

An operator investigating a Run or Track must currently combine container
output, API responses, and direct persistence knowledge. The live health check
only proves that the API process can answer a request; it does not distinguish
PostgreSQL, RustFS, and the mounted Dataset Store. The normal Core runtime also
opens dependencies that are irrelevant to state diagnosis, so an unavailable
object store can obstruct investigation of Product State that remains readable
in PostgreSQL.

This makes a common operational question unnecessarily expensive: given a
ResearchRun ID or DailyTrack ID, determine within ten minutes whether the
resource is queued, running, retrying, blocked, terminal, stale, or published;
which phase and Attempt it reached; and what safe failure category explains the
outcome.

The product is still in development and does not need a hosted observability
platform. Adding OpenTelemetry, a collector, metrics, dashboards, alerts, or a
second event store now would create more operating surface than the problem
requires. The first layer must work end to end using current dependencies while
keeping PostgreSQL authoritative and preventing private research inputs,
credentials, storage locations, and raw payloads from entering logs.

## Solution

Add one basic, private operator observability layer for ThesisTrace Core:

1. Every first-party Core process emits operational events through one
   standard-library logging boundary and one project-owned JSON formatter or
   event sink.
2. API, Research Worker, Tracking Worker, execution child, and Data Operator
   events use one allowlisted envelope and the existing domain identities:
   operation ID, Run ID, Track ID, and Attempt ID. HTTP requests receive a
   separate non-persistent HTTP Request ID.
3. ResearchRun and DailyTrack lifecycle boundaries receive complete structured
   coverage. Data Refresh receives basic start, phase timing, success, and
   failure coverage.
4. A private PostgreSQL-only diagnostic command renders a stable, pretty JSON
   snapshot for one ResearchRun or DailyTrack without opening RustFS or the
   mounted Dataset Store.
5. The existing liveness route remains process-only. A new readiness route
   checks PostgreSQL, RustFS, and the mounted Dataset Store independently and
   reports only stable, safe status codes.
6. Applications write no log files. Containers emit to stdout or stderr and
   Docker Compose owns bounded local rotation. Logs are operational evidence,
   not durable Product State.

The target is intentionally diagnostic rather than analytical. It must let an
operator explain one resource quickly and safely. It does not add a product UI,
telemetry database, distributed tracing backend, metric series, dashboard, or
alerting system.

## User Stories

1. As an operator, I want to diagnose one ResearchRun by Run ID, so that I can explain its current state without manually joining tables.
2. As an operator, I want to diagnose one DailyTrack by Track ID, so that I can explain its Head, pending Advance, and recovery state without manually joining tables.
3. As an operator, I want diagnosis to complete from PostgreSQL while RustFS is unavailable, so that the dependency being investigated cannot hide readable Product State.
4. As an operator, I want a diagnostic snapshot to include every Attempt in chronological order, so that retries and previous failures remain visible.
5. As an operator, I want the current Attempt phase and committed progress shown separately from terminal publication, so that in-flight work is not mistaken for durable output.
6. As an operator, I want heartbeat and lease facts shown with a database-time-derived live or expired classification, so that process liveness is not inferred from recent logs.
7. As an operator, I want retry eligibility, retry timing, and blocked state visible, so that I know whether the system will continue automatically or needs intervention.
8. As an operator, I want Result Bundle or Tracking Checkpoint presence summarized without reading its payload, so that publication can be confirmed safely.
9. As an operator, I want a missing Run or Track to return a stable nonzero result, so that scripts can distinguish absence from a failed resource.
10. As an operator, I want a failed resource to remain a successful diagnostic command, so that the command exit status describes diagnosis rather than business outcome.
11. As an operator, I want one structured lifecycle event format across Core processes, so that I do not need process-specific parsers.
12. As an operator, I want every lifecycle event to identify its component and event name, so that output can be filtered without parsing prose.
13. As an operator, I want ResearchRun events correlated by Run and Attempt, so that claims, phases, retry, publication, and terminal state form one timeline.
14. As an operator, I want DailyTrack events correlated by Track and Attempt, so that Advance, retry, blocking, Checkpoint publication, and Stop form one timeline.
15. As an operator, I want Data Refresh events correlated by operation, so that market and financial phase duration and outcome can be separated.
16. As an operator, I want normal claims, transitions, phase completion, and publication logged at INFO, so that ordinary progress is visible without debug output.
17. As an operator, I want retryable failures, retry scheduling, and operator-actionable blocking logged at WARNING, so that degraded work stands out from normal progress.
18. As an operator, I want unexpected or terminal internal failure logged at ERROR, so that unrecoverable defects are prominent.
19. As an operator, I want idle polling and successful heartbeat renewals omitted from production INFO output, so that useful events are not buried in noise.
20. As an operator, I want DEBUG disabled by default, so that production output remains bounded and deliberate.
21. As an operator, I want one completion event for each non-health HTTP request, so that route, status, and latency are visible without duplicate start and finish noise.
22. As an operator, I want HTTP events to use normalized route templates rather than raw URLs, so that identifiers and query values do not leak or create unbounded dimensions.
23. As an operator, I want the server-generated HTTP Request ID returned in the response, so that a reported request can be found in container logs.
24. As an operator, I want HTTP Request ID kept distinct from the domain request_id idempotency key, so that the two contracts cannot be confused.
25. As an operator, I want expected validation, authorization, conflict, and other domain errors logged without a stack trace, so that routine client outcomes do not look like defects.
26. As an operator, I want an unexpected server exception represented by a sanitized stack once at its handling boundary, so that code location is available without duplicated or private exception data.
27. As a security maintainer, I want logging context controlled by an allowlist, so that arbitrary request or domain objects cannot be serialized accidentally.
28. As a security maintainer, I want tokens, credentials, cookies, authorization headers, DSNs, query strings, bodies, and responses excluded from operational events, so that logs are not a secret store.
29. As a research user, I want Formulae, Hypotheses, and private result payloads excluded from operational events and diagnosis, so that observability does not disclose research content.
30. As a storage operator, I want physical filesystem paths, object keys, SQL text, and raw dependency errors excluded, so that topology and sensitive data are not exposed.
31. As an operator, I want safe domain failure codes preserved, so that failures remain actionable after raw messages are removed.
32. As an operator, I want a liveness result that depends only on the API process, so that orchestration does not restart a healthy process because a dependency is temporarily unavailable.
33. As an operator, I want readiness to report PostgreSQL, RustFS, and the mounted Dataset Store independently, so that the failed dependency is immediately identifiable.
34. As an operator, I want readiness to return unavailable when any required dependency is unusable, so that traffic is not sent to an incomplete Core.
35. As a data operator, I want an empty Dataset Head to remain ready when storage itself is mounted and readable, so that a valid pre-bootstrap state is not reported as infrastructure failure.
36. As an operator, I want Worker availability excluded from API readiness, so that the API dependency contract is not conflated with queue capacity.
37. As an operator, I want health probe requests omitted from routine request logs, so that probe frequency does not dominate application evidence.
38. As a local developer, I want logs available through the existing Compose log workflow, so that no new log viewer is required.
39. As a local developer, I want stopping containers to retain their logs, so that ordinary development shutdown does not erase immediate evidence.
40. As a local developer, I want reset, container removal, and configured rotation documented as destructive to log history, so that temporary logs are never mistaken for an audit trail.
41. As a platform operator, I want application containers to emit only stdout and stderr, so that another runtime can own collection and retention later without changing business code.
42. As a maintainer, I want supervisor-child protocol messages kept separate from operational logs, so that telemetry cannot corrupt execution acknowledgements or results.
43. As a maintainer, I want Data Operator result output kept separate from operational events, so that scripts retain a clean machine-readable command result.
44. As a maintainer, I want lifecycle events emitted only after the represented transaction or publication boundary succeeds, so that logs do not claim state that rolled back.
45. As a maintainer, I want telemetry loss or rotation to have no effect on claim, lease, retry, fencing, recovery, cancellation, Stop, or publication decisions, so that Product State remains correct without logs.
46. As a test maintainer, I want log and diagnostic JSON treated as explicit contracts, so that accidental field drift or leakage fails before release.
47. As a test maintainer, I want real PostgreSQL and RustFS failure and recovery exercised, so that readiness and PostgreSQL-only diagnosis are proven at their actual dependency boundaries.
48. As a release owner, I want the final Production Image to expose the diagnostic command, liveness, readiness, and structured events, so that source-only tests cannot overstate operability.
49. As a release owner, I want secret canaries checked across logs, readiness, diagnostic output, and failure artifacts, so that observability cannot regress confidentiality.
50. As a product maintainer, I want this capability to remain private and absent from the Browser UI, so that a basic operator tool does not become an unfinished customer feature.

## Implementation Decisions

### Authority and scope

- PostgreSQL Product State remains the sole authority for ResearchRun,
  ResearchRun Attempt, DailyTrack, Tracking Advance, Tracking Advance Attempt,
  retry, lease, fence, Checkpoint, and Result lifecycle.
- Structured logs are disposable diagnostic evidence. They are never replayed,
  queried, or interpreted to reconstruct Product State and never participate in
  business decisions.
- Readiness is an infrastructure admission signal, not Product State.
  Diagnostic output is a read-only projection of Product State, not another
  persisted model.
- The implementation covers first-party Core backend processes: API, Research
  Worker, Tracking Worker, supervised execution children, and Data Operator.
  Browser telemetry is outside this layer.
- The implementation is a hard cut from mixed direct printing and ad hoc
  logging to one current operational event contract. There is no compatibility
  formatter, dual event schema, fallback sink, or migration path.

### Structured event contract

- Use Python standard-library logging with one project-owned JSON formatter and
  a small event-emission boundary. Do not add structlog or an OpenTelemetry
  dependency.
- Each operational event is one UTF-8 JSON object on one line.
- Every event has exactly these common required fields:
  - timestamp: UTC RFC 3339 time with millisecond precision.
  - level: one of DEBUG, INFO, WARNING, or ERROR.
  - component: the emitting Core component.
  - event: a stable lower-snake-case event name.
- The common optional correlation fields are operation_id, run_id, track_id,
  attempt_id, and http_request_id. An event includes only the identities that
  exist at its boundary.
- Event-specific context is selected from an explicit allowlist. The initial
  safe vocabulary is worker_role, phase, previous_status, status, outcome,
  attempt_number, duration_ms, retry_at, lease_expires_at, failure_code,
  method, route, status_code, exception_type, and stack_frames. New fields
  require an explicit contract and leakage test rather than serializing
  arbitrary keyword arguments.
- Unknown logging extras, object representations, exception messages, and local
  variables are not copied into the JSON event.
- First-party event names and fields are semantic contracts. Internal Python
  logger names, class names, and function names are not event identities.
- Event timestamps describe emission time. Durable lifecycle timestamps in
  diagnosis come from Product State and are not reconstructed from events.

### Correlation and HTTP behavior

- The existing operation_id, run_id, track_id, and attempt_id identities are
  propagated to every event produced inside their work boundary.
- The existing domain request_id remains an idempotency identity. It is neither
  renamed nor reused as an observability correlation identifier and is not
  included in the log allowlist.
- The API generates a new opaque HTTP Request ID for every request. It is not
  persisted and does not influence idempotency or domain behavior.
- The API returns the generated value in the X-Request-ID response header and
  records it in the one HTTP completion event.
- The HTTP completion event is named http_request_completed and contains only
  HTTP Request ID, method, normalized route template, response status, and
  duration in milliseconds. It contains no raw path, URL, query, headers, body,
  or response payload.
- Liveness and readiness requests emit no routine completion event.
- Expected 4xx and named domain outcomes emit the completion event without a
  stack. Unexpected server failures additionally emit one ERROR event at the
  outer handling boundary.
- A sanitized unexpected-exception representation contains exception type and
  stack frames reduced to module, function, and line number. It contains no
  exception message, physical path, source line, locals, chained payloads, or
  duplicate inner-boundary stack.

### Lifecycle coverage and levels

- ResearchRun coverage includes claim, Attempt start, meaningful state
  transition, phase completion, Checkpoint commit, retry scheduling, Result
  publication, cancellation confirmation, and terminal success or failure.
- DailyTrack coverage includes claim, Advance and Attempt start, meaningful
  state transition, phase completion, retry scheduling, blocking, Tracking
  Checkpoint publication, Stop confirmation, and terminal failure.
- Data Refresh coverage includes operation start, market phase completion,
  financial phase completion, validation and publication completion, total
  outcome, and failure.
- A success event is emitted only after its database transaction, object
  publication, or other represented boundary commits successfully.
- INFO represents normal lifecycle progress and successful HTTP or expected
  client outcomes. WARNING represents a retryable failure, scheduled retry,
  dependency degradation, or operator-actionable blocked state. ERROR represents
  an unexpected server failure or terminal internal failure.
- DEBUG is disabled by default. Idle queue polls, no-work polls, successful
  lease heartbeats, and repeated unchanged readiness probes are not INFO events.
- Lease expiry is determined from PostgreSQL current time and lease_expires_at.
  The presence or recency of telemetry is never a liveness input.

### Process output boundaries

- Long-running API and Worker processes write operational JSON events to their
  container output stream.
- Supervised child stdout remains reserved for the existing parent-child
  protocol. It is not passed through the operational formatter or exposed as
  container telemetry.
- A supervised child emits operational events to stderr with inherited
  correlation context, or reports an allowlisted lifecycle fact to the
  supervisor for canonical emission. Raw child payloads are never forwarded as
  logs.
- Data Operator stdout remains reserved for its machine-readable command
  result. Its operational events use stderr through the canonical formatter.
- The diagnostic command reserves stdout for the requested pretty JSON
  snapshot. Safe invocation and dependency errors use stderr.
- No Core process creates, appends, or rotates an application log file.

### PostgreSQL-only diagnostic command

- Add one private console command named thesistrace-core-diagnose with exactly
  two resource subcommands:
  - thesistrace-core-diagnose research-run RUN_ID
  - thesistrace-core-diagnose daily-track TRACK_ID
- The command uses the normal PostgreSQL configuration but opens no RustFS
  client, Publication store, Dataset Store, Worker, or complete Core runtime.
- Resource-owned diagnostic queries stay within the ResearchRun and DailyTrack
  modules. The command composes their read models and does not own cross-domain
  SQL.
- Output is stable, indented JSON with sorted object keys. Timestamps are UTC
  RFC 3339 strings. Absent optional values are explicit nulls; presence checks
  are explicit booleans.
- Both resource snapshots contain diagnosed_at from PostgreSQL time, resource
  identity and status, progress, a chronological attempts array, recovery
  state, and publication state.
- A ResearchRun snapshot includes Research Kind, current phase, committed
  progress, all ResearchRun Attempts, heartbeat and lease facts, retry state,
  private Checkpoint presence, and Result Bundle presence.
- A DailyTrack snapshot includes authoritative Head, active or latest Tracking
  Advance, frozen Target summary, Tracking Progress, all relevant Attempts,
  heartbeat and lease facts, retry Cycle and blocked state, and Tracking
  Checkpoint presence.
- Attempt entries expose identity, ordinal, status, phase, start and finish
  times, heartbeat and lease expiry, database-time-derived lease_state, retry
  timing, and sanitized failure_code when those facts exist.
- Diagnosis never returns Formula, Hypothesis, command payload, Checkpoint or
  Result content, raw stack, exception message, SQL, DSN, object key, or
  physical storage path.
- Exit code 0 means a valid snapshot was produced, even when the resource itself
  is failed, blocked, cancelled, or stopped. Exit code 2 is invalid command
  usage, 3 is resource not found, and 4 is PostgreSQL unavailable or the
  diagnostic query failed.

### Liveness and readiness

- The existing GET /health/live route remains dependency-free and returns 200
  when the API process can serve requests.
- Add GET /health/ready. It checks PostgreSQL, RustFS, and the mounted Dataset
  Store independently within bounded time.
- PostgreSQL readiness performs a minimal database round trip. RustFS readiness
  reuses the current storage availability boundary without listing or returning
  private objects. Dataset Store readiness proves that the configured mounted
  root exists and is readable.
- A mounted and readable Dataset Store with no current Dataset Head is ready.
  Data coverage and bootstrap completeness are product state, not
  infrastructure readiness.
- Worker process presence, queue backlog, Dataset coverage, and existence of a
  Result or Tracking Checkpoint are not readiness checks.
- The route returns 200 only when all three checks are ready and 503 otherwise.
  Its JSON contains one overall status and one entry per dependency with only a
  status and stable code.
- Success codes are POSTGRESQL_READY, RUSTFS_READY, and
  DATASET_STORE_READY. Failure codes are POSTGRESQL_UNAVAILABLE,
  RUSTFS_UNAVAILABLE, and DATASET_STORE_UNAVAILABLE. Responses contain no raw
  dependency error, endpoint, credential, bucket name, or path.

### Log ownership and retention

- Docker or the deployment runtime owns log collection and retention. The
  application owns event meaning and safe serialization only.
- Local Compose applies the Docker json-file driver with max-size 10m and
  max-file 3 to every managed service, so each container has a bounded local
  history.
- Developers read current logs through the existing development log command or
  ordinary Compose tooling. The repository contains no log directory.
- Stopping a container preserves its Docker-managed history. Rotation,
  container recreation or deletion, and the development reset or erase
  lifecycle may remove that history.
- A later hosted deployment may replace the collector or retention policy
  without changing the event contract or Product State semantics.

### Documentation and delivery

- Record the architectural authority boundary in ADR-0217.
- Do not add Observability, Log, Liveness, or Readiness to the domain glossary;
  they are generic engineering terms rather than ThesisTrace domain language.
- When implementation exists, update the Core architecture and operator
  runbook with the actual event contract, diagnostic commands, health semantics,
  local log access, rotation, and destructive lifecycle boundaries.
- Do not document dashboards, alerts, long-term retention, or hosted collection
  that the implementation does not provide.

## Testing Decisions

- Tests assert emitted events, response contracts, diagnostic snapshots, exit
  codes, and durable state relationships rather than private formatter classes
  or logging call counts.
- Formatter contract tests prove one event per line, valid JSON, required
  envelope fields, UTC timestamps, allowed levels, stable names, and omission
  of every unknown extra.
- Leakage tests inject canary tokens, passwords, authorization headers, cookies,
  DSNs, URLs, query strings, Formulae, Hypotheses, paths, object keys, raw
  exception messages, and payloads, then assert that none appears in captured
  stdout, stderr, readiness, diagnosis, or failure artifacts.
- HTTP contract tests prove one completion event for success, validation,
  conflict, not-found, and unexpected failure; normalized routes; response
  X-Request-ID; distinct HTTP and domain request identities; no body or query;
  no health-request event; and the expected stack policy.
- Worker tests extend the existing injectable event-sink seam and assert
  correlation and semantic events without binding business services to a
  global logger.
- Real PostgreSQL integration tests exercise ResearchRun claim, multi-phase
  progress, Checkpoint commit, retry, terminal publication, cancellation,
  DailyTrack Advance, blocking, retry Cycle, Checkpoint publication, and Stop.
  They assert that emitted events agree with committed Product State.
- Heartbeat tests prove that successful renewals do not create INFO noise and
  that diagnostic lease_state changes only when PostgreSQL time crosses
  lease_expires_at.
- Diagnostic command integration tests use real PostgreSQL and fixtures with
  zero, one, and several Attempts; current, expired, retrying, blocked, failed,
  cancelled, stopped, and published states; explicit nulls; stable ordering;
  not found; and database failure.
- A diagnostic test makes RustFS and the Dataset Store unavailable while
  PostgreSQL remains available and proves that both resource commands still
  return their snapshots without attempting those dependencies.
- Readiness integration tests fail and recover PostgreSQL, RustFS, and the
  mounted Dataset Store independently. They verify 200 versus 503, exact safe
  codes, bounded completion, and the ready empty-Head state.
- Data Operator tests cover market, financial, validation, and publication
  phase timing plus overall success and sanitized failure, while preserving
  clean machine-readable stdout.
- Child-process tests prove that protocol stdout remains parseable and
  operational events cannot enter the protocol stream.
- Compose architecture tests verify bounded rotation for every service,
  liveness remains the process probe, and readiness is used only where
  dependency readiness is intended.
- Production Image smoke proves the packaged diagnostic console command,
  liveness, readiness, API request event, Research Worker event, Tracking Worker
  event, Data Operator event, dependency failure and recovery, and absence of
  secrets in collected output.
- Tests use fixed clocks, stable IDs, isolated Compose projects, bounded
  condition polling, and real owned dependencies. They use no public data
  service and no arbitrary sleep.
- The ordinary local test command must execute all new fast formatter, HTTP, and
  diagnostic contract tests. No new entrypoint-only test directory may be
  created without wiring it into that command.
- This feature adds no browser E2E because it has no Browser surface and adds no
  long-history benchmark because it changes no calculation or performance
  contract.

## Out of Scope

- OpenTelemetry SDKs, traces, spans, collectors, exporters, and context
  propagation standards.
- Prometheus or other metric series, dashboards, alert rules, paging, SLOs, and
  hosted observability vendors.
- A log database, search cluster, event bus, audit ledger, outbox, or permanent
  log archive.
- A Worker Registry, queue-capacity health check, automatic remediation, or
  orchestration policy.
- A Browser observability page, admin console, customer-visible status page, or
  public diagnostic API.
- Persisting HTTP Request ID or adding it to Product State.
- Replacing domain request_id idempotency semantics.
- Returning raw Checkpoint, Result, Formula, Hypothesis, request, response,
  object-store, or Dataset payloads through logs or diagnosis.
- Using log recency to infer Attempt ownership, liveness, lease validity,
  retry, publication, or recovery.
- Changing ResearchRun, DailyTrack, Data Refresh, Worker scheduling, retry,
  cancellation, Stop, Publication, or data semantics.
- Application-owned log files, unbounded Docker logs, or a retention guarantee
  across container deletion and development reset.
- Authentication, tenants, hosted deployment topology, or remote operator
  access.
- Backward-compatible log formats, event-schema migrations, dual emission, or
  fallback readers.

## Further Notes

- The expected implementation size is four to six person-days, approximately
  900 to 1,500 changed lines across 16 to 24 files, including tests and
  documentation.
- The likely delivery sequence is: canonical event boundary and API request
  completion; lifecycle instrumentation; PostgreSQL-only diagnosis; readiness
  and Compose retention; then Production Image smoke and truthful operator
  documentation. Each step should leave one working current path rather than
  retain the superseded output path.
- Existing Worker event injection, real dependency acceptance fixtures,
  liveness tests, secret-leakage checks, and Production Image smoke are the
  closest testing patterns to extend.
- Container logs are intentionally short-lived evidence. An incident that needs
  history beyond local rotation requires a later explicit collection and
  retention decision, not hidden application persistence.
- This Spec is ready to be decomposed into implementation issues.

## Comments
