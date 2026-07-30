Status: ready-for-agent

# ThesisTrace Hosted Platform V2

## Problem Statement

ThesisTrace V1 proves reproducible research for one operator, but it does not
provide a safe hosted product for multiple independent Users. An invited User
needs to register, receive one private Personal Workspace, submit durable work,
and inspect bounded product results without seeing another User's resources or
the platform's raw storage. The Operator needs to run this product on one
cost-conscious node without introducing a custom scheduler, unbounded compute,
unclear ownership, or operational claims that the deployment cannot meet.

The hosted release must preserve a strict distinction between platform-owned
Dataset Releases and Personal Workspace-owned research resources. It must also
survive request retries, process crashes, worker redelivery, maintenance, and
single-node restarts without duplicating domain work or publishing partial
results. Authentication alone is insufficient: API authorization, PostgreSQL
row-level security, quotas, storage admission, scheduling, and operational
evidence must enforce the same boundary.

## Solution

Build Hosted Platform V2 as one version-pinned Docker Compose deployment on a
6-core, 12-GiB node with a 200-GB persistent SSD. Cloudflare and Caddy expose
one browser Origin containing the production Web application, the ThesisTrace
API, and only the required public InsForge Auth routes. InsForge Auth owns
registration credentials, login, email verification, sessions, and password
recovery. ThesisTrace owns invitation authorization, the
User-to-Personal-Workspace mapping, product authorization, quotas, and all
research-resource lifecycle state.

Each authenticated User owns exactly one Personal Workspace. PostgreSQL stores
identity mappings, ownership, lifecycle, quota, idempotency, scheduling, audit,
and immutable-object indexes. Platform-owned Dataset Releases are shared
read-only across Personal Workspaces; private research artifacts remain owned
by exactly one Personal Workspace. Bulk immutable bytes remain behind a
private ObjectStore boundary. Users receive bounded product views through the
ThesisTrace API and never receive a raw object-download endpoint, object-store
credential, signed object URL, or public InsForge Storage route.

Temporal provides durable finite Workflows, Activity delivery, retries,
heartbeats, cancellation, and crash recovery. Four one-slot Compute Workers
share the global Compute capacity, while one separate one-slot Data Worker
executes Dataset Publication. Automatic Tracking work is preferred over P3
User Compute, but preference may not starve P3: whenever both tiers remain
queued, at least one of the four Compute slots is logically reserved for P3
progress while the other three prefer P1. The reservation is work-conserving:
either tier may use all four slots when the other tier has no queued work.
Personal Workspace fairness applies within each tier, and running Activities
are never preempted.

The hosted product is accepted primarily through one black-box test seam: a
complete production-like single-node Compose stack exercised only through its
public Origin. Two narrower seams cover guarantees that the public boundary
cannot prove reliably: real PostgreSQL RLS contract tests and a real Temporal
deterministic dispatch probe.

## User Stories

1. As an invited User, I want to register with my email and password, so that I can access ThesisTrace without a separate ThesisTrace credential.
2. As an invited User, I want InsForge to verify my email, so that ThesisTrace does not invent a second identity-verification flow.
3. As an invited User, I want a valid Registration Invitation to authorize my first registration, so that public Personal Workspace creation remains closed.
4. As an invited User, I want an expired or revoked Registration Invitation to fail clearly, so that old authorization cannot be reused.
5. As an invited User, I want a registration retry to return my same User and Personal Workspace, so that a network failure does not create duplicates.
6. As an invited User, I want concurrent attempts to consume one Registration Invitation to produce only one successful provisioning result, so that invitation use is truly single-use.
7. As a User, I want to log in through InsForge Auth, so that ThesisTrace never receives my password.
8. As a User, I want InsForge to own password recovery, so that I do not encounter a competing ThesisTrace recovery mechanism.
9. As a User, I want exactly one Personal Workspace provisioned for my identity, so that ownership is simple and deterministic.
10. As a User, I want every private research resource to belong to my Personal Workspace automatically, so that I never select or submit a Personal Workspace identifier.
11. As a User, I want another User's resource identifiers to reveal no data, so that guessing an identifier cannot cross the Personal Workspace boundary.
12. As a User, I want list, read, create, update, run, cancel, stop, and delete operations constrained to my Personal Workspace, so that all product workflows share one isolation rule.
13. As a User, I want platform-owned Dataset Releases available read-only, so that every Personal Workspace can reproduce research without duplicating ingestion.
14. As a User, I want no ability to mutate or publish a Dataset Release, so that shared market-data truth remains platform-owned.
15. As a User, I want to request a ResearchRun asynchronously, so that an HTTP request is not held open by heavy calculation.
16. As a User, I want repeated submission of the same idempotent request to create one ResearchRun, so that retries do not consume duplicate capacity.
17. As a User, I want durable queued, running, succeeded, failed, and cancelled product states, so that process restarts do not erase the state I see.
18. As a User, I want a sanitized stable failure code and useful product message, so that I can act without seeing infrastructure secrets or another Personal Workspace's details.
19. As a User, I want cancellation to stop eligible work cooperatively and prevent late publication, so that a delayed Worker cannot publish a cancelled result.
20. As a User, I want a rerun to create a new domain resource while infrastructure retry remains an Attempt of the existing resource, so that intent and recovery stay distinct.
21. As a User, I want a successful Run published atomically, so that I never observe a partial result.
22. As a User, I want result summaries and supported time-series views through the ThesisTrace API, so that I can use the product without understanding object storage.
23. As a User, I want every collection and time-series response bounded and paginated where necessary, so that one request cannot materialize an unbounded payload.
24. As a User, I want no raw artifact, manifest-object, or storage-bucket download surface, so that internal encodings and object keys are not product contracts.
25. As a User, I want an active DailyTrack to advance after a successful Dataset Release, so that my accepted research remains current.
26. As a User, I want Tracking work preferred over ordinary User Compute, so that routine research demand does not indefinitely delay daily continuity.
27. As a User waiting for a P3 ResearchRun, I want bounded dispatch progress even while P1 Tracking remains queued, so that sustained Tracking demand cannot starve my accepted work.
28. As a User, I want scheduling fairness among active Personal Workspaces within the same priority tier, so that one backlog cannot monopolize dispatch.
29. As a User, I want running work left uninterrupted by later higher-priority work, so that priority does not corrupt execution or cause wasteful preemption.
30. As a User, I want otherwise idle Compute capacity used immediately, so that fairness and priority do not leave Worker slots idle.
31. As a User, I want active DailyTracks constrained by the Quota Profile hard maximum, so that continued tracking has a clear product limit.
32. As a User, I want queued or running User Compute limited to eight jobs, so that my own backlog remains bounded.
33. As a User, I want private immutable storage limited to 10 GiB, so that storage admission is predictable.
34. As a User, I want a quota rejection to identify the exceeded dimension, so that I know whether to stop a Track, wait for work, or delete stored results.
35. As a User, I want quota changes to affect new admissions and writes without deleting history or cancelling running work, so that an Operator adjustment is not destructive.
36. As a User, I want a stopped DailyTrack to release its active-Track quota, so that I can replace it with a different Track.
37. As a User, I want deletions limited to terminal ResearchRuns and stopped DailyTracks, so that active work cannot lose its authoritative state.
38. As a User, I want deletion to remove the complete resource rather than mutate immutable artifacts, so that retained artifacts remain trustworthy.
39. As a User, I want deletion to become unreadable immediately and retry physical cleanup safely, so that backend cleanup failure does not restore product access.
40. As a User, I want private storage quota released only when physical cleanup succeeds, so that quota accounting matches retained bytes.
41. As a User, I want a deleted resource to remain represented only by a minimal Resource Tombstone, so that deletion is auditable without retaining the result payload.
42. As a User, I want API request-rate limits distinct from durable-work quotas, so that a short request burst is not reported as exhausted storage or Compute capacity.
43. As a User, I want reads, cancellation, and deletion to remain available under storage pressure, so that I can inspect and reduce usage.
44. As a User, I want new payload-growing work rejected before the node becomes unsafe, so that accepted results are not corrupted by a full disk.
45. As a User, I want previously published resources to remain available after a failed new publication, so that one failed attempt cannot replace known-good truth.
46. As an Operator, I want to issue a Registration Invitation for one normalized email address, so that registration authority has an explicit target.
47. As an Operator, I want every Registration Invitation to have an explicit expiry selected at issue time, so that validity is bounded without hard-coding one product-wide TTL.
48. As an Operator, I want to revoke an unused Registration Invitation, so that access can be withdrawn before registration.
49. As an Operator, I want issue, revoke, expire, consume, and failed-consumption outcomes audited, so that registration authorization is traceable.
50. As an Operator, I want invitation consumption and User/Personal Workspace provisioning committed atomically in ThesisTrace, so that a consumed invitation cannot point to missing product ownership.
51. As an Operator, I want one audited administrative CLI rather than a public Admin UI, so that first-release administration has a narrow surface.
52. As an Operator, I want to apply lower-only active-DailyTrack overrides and other explicit Quota Profile overrides, so that exceptional limits remain auditable without introducing plans or billing.
53. As an Operator, I want one durable Dataset Publication Workflow and one Data Worker slot, so that source ingestion cannot overlap with itself.
54. As an Operator, I want Dataset Publication isolated from the four Compute slots, so that User work neither blocks nor consumes the platform publication executor.
55. As an Operator, I want four independent one-slot Compute Workers, so that one crash or memory exhaustion affects one Activity instead of the whole pool.
56. As an Operator, I want Compute concurrency to be deployment configuration initially set to four, so that measured capacity can change without changing research semantics.
57. As an Operator, I want every heavy operation represented by a finite Temporal Workflow, so that Workflow history does not grow with the lifetime of a DailyTrack.
58. As an Operator, I want PostgreSQL to remain product truth and Temporal to remain execution truth, so that the scheduler does not become a second domain database.
59. As an Operator, I want an execution outbox to bridge the PostgreSQL and Temporal commit boundary, so that a crash cannot silently lose accepted work.
60. As an Operator, I want Activity retries, heartbeats, timeouts, and redelivery handled by Temporal, so that ThesisTrace does not maintain a parallel lease scheduler.
61. As an Operator, I want every external Activity write idempotent and final publication fenced, so that at-least-once execution cannot create duplicate truth.
62. As an Operator, I want resource-exhausted Activities retried at most once automatically, so that an oversized job cannot enter an unbounded restart loop.
63. As an Operator, I want repeated resource exhaustion classified separately from quota or research validation, so that capacity faults remain diagnosable.
64. As an Operator, I want temporary and unreferenced objects removed after failed work, so that failures do not consume permanent storage.
65. As an Operator, I want PostgreSQL metadata separated from immutable bulk objects, so that lifecycle queries do not load large result payloads.
66. As an Operator, I want object access mediated by a private ObjectStore port, so that application contracts do not depend on host paths or one storage backend.
67. As an Operator, I want InsForge Storage private to application services, so that users cannot bypass API authorization or quota accounting.
68. As an Operator, I want Cloudflare to be the external public edge and Caddy the only container binding application ports, so that the origin has one controlled ingress path.
69. As an Operator, I want the origin firewall to accept Web traffic only from Cloudflare proxy ranges, so that clients cannot bypass edge controls.
70. As an Operator, I want coarse Auth-route rate limits at Cloudflare and authenticated product-route limits in the API, so that abuse controls match identity availability.
71. As an Operator, I want PostgreSQL, Storage, Temporal, workers, dashboards, metrics, and administration endpoints kept off the public network, so that infrastructure is not a tenant API.
72. As an Operator, I want separate service identities, database roles, network paths, and secrets for API, relay, Data Worker, and Compute Workers, so that one compromised role does not gain every capability.
73. As an Operator, I want Compute Workers to have no Tushare or general Internet access, so that only the Data Worker can reach the sole market-data source.
74. As an Operator, I want Workers to run non-root with read-only roots and bounded scratch space, so that shared execution has a constrained operating-system boundary.
75. As an Operator, I want liveness and readiness to remain cheap and role-specific, so that health probes do not create storage writes or expensive workloads.
76. As an Operator, I want separate System Health, Data Health, and Quantitative Semantic Health dashboards, so that infrastructure availability is not mistaken for data or result correctness.
77. As an Operator, I want low-cardinality metrics and sanitized correlated logs and traces, so that observability remains useful without leaking User research or credentials.
78. As an Operator, I want bounded local metrics and log retention with external sampled traces, so that observability cannot consume the node indefinitely.
79. As an Operator, I want failed task traces retained more aggressively than successful traffic traces, so that limited telemetry favors diagnosis.
80. As an Operator, I want to inspect the three dashboards at least daily, so that the first release has an explicit detection practice without pretending to provide paging.
81. As an Operator, I want encrypted coordinated off-node backups every six hours with seven-day expiry, so that the single node has bounded disaster recovery.
82. As an Operator, I want a restore to reconcile Resource Tombstones before reopening, so that disaster recovery cannot resurrect deleted payloads.
83. As an Operator, I want a real recovery exercise before inviting Users, so that backup existence is not mistaken for recoverability.
84. As an Operator, I want version-pinned one-shot migrations to finish before steady services start, so that application startup cannot hide schema changes.
85. As an Operator, I want release bundles to pin compatible Web, API, Worker, InsForge, Temporal, and migration versions, so that deployment and rollback never mix arbitrary components.
86. As an Operator, I want expand-contract schema changes and the previous release bundle retained, so that ordinary rollback avoids unsafe reverse migrations.
87. As an Operator, I want admission paused and running Activities drained during maintenance, so that migration does not cross an uncontrolled execution boundary.
88. As an Operator, I want maintenance-interrupted Activities recoverable without being mislabeled failed or resource-exhausted, so that release work does not alter User intent.
89. As an Operator, I want a production Web build served by Caddy with no long-running Vite server, so that development tooling is absent from the deployment.
90. As an Operator, I want representative maximum workloads to pass the accepted Worker and host envelope, so that invited Users do not become the capacity test.
91. As an Operator, I want direct-origin, cross-Personal-Workspace, retry, restart, and partial-publication failures exercised before release, so that core platform boundaries have executable evidence.
92. As an Operator, I want hosted shared use of Tushare-backed Dataset Releases enabled only after the deployment records suitable source authorization, so that the platform does not promise data use beyond its upstream rights.

## Implementation Decisions

- The first hosted tenant model is `User -> exactly one Personal Workspace`.
  Personal Workspaces have no members, sharing, Organization parent, Project
  hierarchy, or RBAC roles. The server derives the Personal Workspace from the
  verified User identity; clients never choose it.
- InsForge Auth is the only end-User identity and session provider. Browsers use
  its public email-and-password registration, login, email-verification, and
  password-recovery routes. ThesisTrace stores no password, verifies no
  password, issues no parallel session, and implements no recovery token.
- A Registration Invitation has a unique opaque identity, normalized bound
  email, explicit `expires_at`, state, issuing Operator, issue time, and
  optional revocation and consumption facts. Its lifecycle is
  `issued -> consumed | revoked | expired`. The issuing Operator chooses a
  future expiry; this spec defines no fixed invitation TTL.
- Registration requires a verified InsForge identity whose normalized email
  matches one currently issued, unexpired, unrevoked invitation. One
  PostgreSQL transaction atomically consumes that invitation, creates or
  resolves the ThesisTrace User, provisions or resolves exactly one Personal
  Workspace, and records the management audit event. A unique
  invitation constraint, a unique InsForge-identity mapping, and a unique
  User-to-Personal-Workspace mapping make concurrent consumption single-winner
  and retries idempotent.
  Local provisioning failure leaves the invitation unconsumed and retryable;
  successful local commit makes it permanently consumed.
- Public self-service Personal Workspace creation remains disabled. Public
  login and InsForge password recovery remain available to already registered
  Users regardless of invitation state.
- The Operator issues and revokes invitations, applies Quota Profile overrides,
  performs release and recovery operations, and invokes authorized manual
  Dataset Publication through versioned CLI commands over SSH. The first
  release has one trusted Operator, no public Admin UI, and no Operator RBAC.
  Every state-changing administrative command appends a sanitized,
  non-deletable management audit event.
- Platform-owned Dataset Releases are readable by authenticated product
  operations in every Personal Workspace and writable only through Dataset
  Publication. Research Definitions, ResearchRuns, Result Bundles, DailyTracks,
  Tracking Checkpoints, and their lifecycle and usage records are private to
  one Personal Workspace.
- Invited-User launch and real Tushare Dataset Publication require an
  Operator-recorded source-authorization declaration that permits the intended
  hosted shared use. Without it, the deployment may run deterministic fixture
  acceptance but must keep invitation issuance and live publication disabled
  with `SOURCE_AUTHORIZATION_REQUIRED`; ThesisTrace does not infer permission
  merely from possession of a Tushare token.
- InsForge PostgreSQL is authoritative for identity mapping, ownership,
  lifecycle, idempotency, quota accounting, scheduling metadata, the execution
  outbox, immutable-object indexes, deletion state, and management audit.
  Immutable bulk payloads remain outside PostgreSQL behind the ObjectStore
  port. Storage paths and object keys are opaque implementation details.
- Every Personal Workspace-owned product table has a non-null `workspace_id` and
  PostgreSQL RLS. The API verifies the InsForge JWT, resolves the authoritative
  User mapping, and sets transaction Personal Workspace context server-side.
  The API role is not a superuser and has no `BYPASSRLS`; service processes use
  separate least-privilege roles.
- The first hosted release exposes no raw artifact download, result-object
  download, signed object URL, public bucket operation, or public InsForge
  Storage route. The ThesisTrace API resolves authorized manifests internally
  and returns only defined product summaries, detail views, and bounded
  paginated series. API responses never reveal physical paths, storage
  credentials, or directly usable object keys.
- One Cloudflare-proxied hostname provides the single browser Origin. Caddy is
  the only application container binding ports 80 and 443; it serves the
  production Web build and proxies only the versioned ThesisTrace API and the
  required public InsForge Auth routes. PostgreSQL, InsForge Storage and
  administration, Temporal, Workers, Prometheus, Grafana, and OpenTelemetry
  Collector remain private. The origin accepts Web traffic only from verified
  Cloudflare proxy ranges and uses Full (strict) origin TLS.
- Cloudflare applies coarse client-IP limits to public registration, login,
  verification, and recovery routes. The API applies short-window authenticated
  User and Personal Workspace limits, with stricter limits for state-changing
  and task-creating routes. API rate limits return `429` and remain separate
  from Quota Profile enforcement.
- The default Quota Profile has exactly three dimensions:
  `max_active_daily_tracks`,
  `max_nonterminal_user_compute_jobs = 8`, and
  `max_private_storage_bytes = 10 GiB`. Operator overrides are explicit and
  auditable. ADR-0117 is the single source for the active-Track hard maximum,
  whose Personal Workspace override may only lower. Quota changes govern new
  admission and writes without cancelling work or deleting history.
- A terminal ResearchRun or stopped DailyTrack is deletable as a whole. A seed
  Run cannot be deleted while a retained DailyTrack references it. Deletion
  creates a permanent minimal Resource Tombstone, removes live references,
  makes the resource unreadable, and retries physical cleanup idempotently.
  Private-storage quota is released only after physical bytes with no live
  reference are removed.
- Disk pressure is measured against the configured 200-GB persistent SSD.
  Initial thresholds are warning at 70%, rejection of new private
  payload-growing work at 80%, and rejection of all payload-growing work,
  including Dataset Publication, at 90%. Reads, cancellation, deletion,
  cleanup, and the control writes they require remain available. Every
  immutable publication performs final storage and quota checks before its
  authoritative manifest commit.
- The public API transaction for accepted heavy work creates durable domain
  state and an execution-outbox entry. An idempotent relay starts a finite
  Temporal Workflow from a stable domain identity. PostgreSQL remains product
  truth; Temporal Workflow History remains orchestration and delivery state.
  ThesisTrace implements no second claim-and-lease scheduler.
- Finite Workflows cover Dataset Publication, ResearchRun, Tracking Advance,
  explicit equivalence verification, and maintenance-only Tracking Generation
  rebuild. Heavy calculation and side effects run in Activities. Workflow and
  Activity payloads contain only opaque identities, hashes, and small control
  values.
- Four identical, long-lived Compute Worker containers each execute at most one
  heavy Compute Activity. The initial global Compute concurrency is four and
  remains deployment configuration. One separately budgeted Data Worker
  executes at most one Dataset Publication Activity on its own Task Queue and
  does not consume a Compute slot.
- P1 automatic Tracking Advances and P3 ResearchRuns or explicit equivalence
  verification share the Compute pool. Dispatch is work-conserving and does
  not preempt a running Activity. While both tiers have work, one of the four
  global slots is logically reserved for P3 progress and the other three prefer
  P1. When only one tier has work, it may use all four slots. The reservation
  is a Temporal dispatch and Worker-polling contract, not a second PostgreSQL
  scheduler. Equal-weight Personal Workspace fairness and FIFO apply within one
  tier.
- Activities may execute more than once. All external writes are idempotent,
  long Activities heartbeat and cooperate with cancellation, and final
  publication uses compare-and-set and late-publication fencing. A
  resource-exhausted Activity receives at most one automatic retry; a repeated
  failure becomes `RESOURCE_EXHAUSTED` and publishes no partial artifact.
- The single node enforces the accepted resource envelope: each of four
  Compute Workers has a 1-GiB memory hard limit and 0.75-CPU cap; the Data
  Worker has a 1-GiB memory hard limit and 0.5-CPU cap; non-worker services
  together receive at most 5 GiB and 2 CPU cores; at least 2 GiB and 0.5 CPU
  remain outside those budgets for the host. Launch capacity evidence must
  demonstrate representative maximum work under this complete stack before
  invitations are issued.
- Compute Workers run non-root with read-only root filesystems, bounded writable
  scratch, no Docker socket, no privileged capabilities, no physical Storage
  volume mount, and no general Internet or Tushare egress. The Data Worker has
  the separate Tushare egress path. API, relay, Data Worker, Compute Worker,
  Storage, PostgreSQL, Temporal, and telemetry credentials remain
  role-separated.
- The production Web is a type-checked, versioned static build served directly
  by Caddy. Vite is a build and local-development tool, not a steady production
  service. Web, API, Worker, InsForge, Temporal, migrations, and configuration
  form one pinned release bundle.
- InsForge product schema, ThesisTrace schema, and Temporal persistence and
  Visibility schema changes run as explicit version-pinned one-shot jobs before
  steady services. Changes use expand-contract compatibility, and the
  immediately preceding release bundle remains available for rollback.
  Backward-incompatible data changes require a coordinated restore rather than
  an automatic reverse migration.
- Maintenance mode stops new admissions, pauses Temporal Schedules and the
  outbox relay, and gives running Activities up to 15 minutes to drain before
  Workers stop normally. Maintenance interruption does not itself fail or
  cancel domain work and does not consume a resource-exhaustion retry.
- Long-running services expose cheap dependency-independent liveness and
  role-specific readiness. System Health aggregates readiness with queues,
  heartbeats, capacity, Data Health, and Quantitative Semantic Health. Tushare
  or telemetry failure degrades its own capability without falsely declaring
  every product service dead.
- The launch observability stack is OpenTelemetry SDK instrumentation, one
  Collector, Prometheus, Grafana, bounded rotated JSON container logs, and an
  external OTLP trace backend. System Health, Data Health, and Quantitative
  Semantic Health have separate dashboards. Metrics remain low-cardinality,
  and telemetry excludes credentials, email addresses, research expressions,
  market payloads, and result payloads.
- The first release sends no alert notifications. The Operator inspects all
  three dashboards at least once per calendar day. Prometheus retains at most
  seven days or 5 GiB; each container retains at most five 20-MB JSON log
  files; failed task traces are retained at 100%, successful task traces at
  10%, and ordinary successful HTTP traces at 1% for seven days externally.
- Coordinated encrypted off-node backups run every six hours and expire after
  seven days. They include the product database, Temporal persistence and
  Visibility databases, and matching Storage objects. Restore reconciles
  Resource Tombstones and passes platform health checks before public service
  resumes. The launch objectives are at most six hours of lost committed state,
  up to 24 hours to detect through daily inspection, and up to eight hours to
  execute recovery after detection.

## Testing Decisions

- A good Hosted Platform V2 test asserts externally visible ownership,
  lifecycle, idempotency, bounded response, dispatch, publication, and failure
  behavior. It does not assert container implementation details, private
  function calls, incidental SQL shape, object filenames, or Temporal history
  event order unless one of those is itself the explicit contract.
- The primary acceptance seam starts the complete production-like single-node
  Compose stack with pinned Web, Caddy, API, InsForge Auth and Storage,
  PostgreSQL, Temporal, Data Worker, four Compute Workers, Collector,
  Prometheus, and Grafana. Tests act only through the public Cloudflare/Caddy
  Origin or its acceptance-equivalent trusted edge and through the Operator CLI
  where an Operator action is required.
- Public-Origin acceptance covers invitation registration, verified identity,
  login, password-recovery ownership, idempotent Personal Workspace
  provisioning, authenticated product creation, durable asynchronous status,
  cancellation and late-result fencing, quota rejection, bounded product
  result views, deletion and Tombstone behavior, and denial of every raw
  artifact or Storage route.
- Public-Origin acceptance creates two Users and proves negative
  cross-Personal-Workspace behavior for list, read, update, execute, cancel, stop,
  delete, and bounded result-view operations. Tests use valid identifiers from
  the other Personal Workspace and require a non-disclosing denial rather than
  relying only on random nonexistent identifiers.
- Registration tests cover matching and mismatched email, explicit expiry,
  revocation before use, already consumed invitations, two concurrent
  consumers, a retry after interrupted local provisioning, and repeated
  idempotent completion. Exactly one User, one Personal Workspace, and one
  consumed invitation may result from a winning identity.
- One necessary lower seam uses real PostgreSQL with production migrations,
  roles, and RLS policies. It attempts cross-Personal-Workspace reads and
  writes directly through the non-`BYPASSRLS` API role for every Personal
  Workspace-owned table, verifies missing or forged transaction Personal
  Workspace context cannot broaden access, and proves service roles can perform
  only their accepted responsibilities. This is a database contract test, not
  an in-memory or mocked-policy test.
- One necessary lower seam uses a real Temporal Service and the production
  dispatch path with controlled Activities. Its deterministic probe verifies
  global Compute concurrency never exceeds four, Dataset Publication uses only
  the independent one-slot Data Worker, same-tier Personal Workspace fairness
  is work-conserving, and running work is not preempted. With sustained P1 and
  P3 backlogs, at least one of the four active or next-available slots must make
  P3 progress while the other three may prefer P1. The probe repeats the same
  input schedule and requires the same dispatch decisions.
- Temporal recovery tests interrupt the outbox relay, API, Temporal Worker, and
  Activity at each publication boundary. They prove accepted work is eventually
  started once, Activity redelivery does not duplicate domain results,
  cancellation fences late commits, repeated resource exhaustion terminates
  after two executions, and no partial Result Bundle, Dataset Release, or
  Tracking Checkpoint becomes authoritative.
- Storage and quota acceptance checks exact stored compressed bytes through
  authoritative indexes, atomic failure when quota or final disk preflight
  fails, staging cleanup after failure, reference-aware deletion, quota release
  only after physical cleanup, and continued access to the previously
  authoritative result.
- Security acceptance verifies direct-origin rejection, Cloudflare forwarding
  metadata trust only from accepted proxy ranges, no public ports for private
  services, no public InsForge Storage path, no raw or signed artifact URL,
  sanitized User failures, and absence of credentials, email addresses, and
  private research payloads from logs, metrics, traces, and Temporal payloads.
- Capacity acceptance runs the representative maximum workload in one Worker
  and four simultaneous maximum Compute Activities while Dataset Publication
  and all steady services are present. Each Compute Worker must have p99 memory
  at or below 700 MiB, absolute peak at or below 800 MiB, no swap, OOM, or
  unexpected restart, and correct completion under CPU throttling and heartbeat
  timeouts.
- Launch preflight requires the hosted-use source-authorization declaration
  before invitation issuance or live Tushare Dataset Publication. Tests prove a
  Tushare token alone does not satisfy the gate, the stable
  `SOURCE_AUTHORIZATION_REQUIRED` result exposes no credential detail, and
  deterministic fixture acceptance remains available while the gate is closed.
- Deployment acceptance verifies clean installation, migration failure stopping
  steady services, forward deployment, rollback to the immediately preceding
  compatible release, maintenance drain and redelivery, node restart recovery,
  six-hour backup creation, and a full off-node restore that reconciles
  Tombstones before the public Origin reopens.
- Observability acceptance injects one failure in each plane and proves it
  appears on the correct System Health, Data Health, or Quantitative Semantic
  Health view without changing an unrelated readiness signal. It also verifies
  metric cardinality, local retention bounds, trace sampling, dropped-export
  visibility, and non-blocking telemetry failure.
- The existing V1 public-API and Worker acceptance tests are prior art for the
  primary black-box seam. Existing resource-capacity and storage-budget
  prototypes are prior art for measured launch gates, but their synthetic
  encodings or fixture-only paths are not sufficient Hosted Platform V2
  acceptance evidence.

## Out of Scope

- Organizations, shared Personal Workspaces, Personal Workspace members,
  collaboration, resource sharing, Project hierarchies, tenant-admin roles,
  and public administration interfaces.
- Billing, payments, subscriptions, commercial plans, Compute credits, usage
  charging, automatic quota upgrades, and per-day ResearchRun quotas.
- High availability, zero-downtime deployment, rolling migration, multi-node
  application or Temporal clusters, automatic failover, and multi-region
  disaster recovery.
- Raw artifact downloads, manifest downloads, signed object URLs, public
  InsForge Storage routes, user-supplied object keys, filesystem paths, and
  direct browser access to product tables through PostgREST.
- Social OAuth, enterprise SSO, magic-link-only login, ThesisTrace passwords,
  ThesisTrace password recovery, open public registration, and self-service
  Personal Workspace creation.
- Multiple Operators, Operator RBAC, public Grafana, public Temporal UI, and
  user-facing raw logs, metrics, traces, stack traces, or host diagnostics.
- Email, PagerDuty, Slack, SMS, or other alert delivery. Dashboard warnings and
  daily Operator inspection are the first-release notification boundary.
- Redis or another distributed rate-limit store, a custom scheduler, a
  PostgreSQL claim-and-lease loop, a generic message broker, or a permanent
  Temporal Workflow per DailyTrack.
- MinIO, RustFS, a public S3 API, dynamic secret-management infrastructure,
  GPU Workers, per-User Worker containers, parameter sweeps, and generic
  portfolio optimization.
- Changes to Alpha, Factor Evaluation, Strategy Backtest, Dataset Publication,
  Daily Tracking, historical-correction, or quantitative numeric semantics.
  Those contracts belong to the referenced research and storage specs.
- New asset classes, new market-data providers, changes to the Tushare-only
  source boundary, and changes to Dataset Release content.
- Obtaining, negotiating, or interpreting Tushare commercial or redistribution
  rights. The Operator supplies the authorization declaration; ThesisTrace
  enforces the launch gate but does not provide legal advice.

## Further Notes

- The ThesisTrace V1 Reproducible Research Platform Spec remains authoritative
  for research authoring, market-data, Alpha, Factor Evaluation, Strategy
  Backtest, and Daily Tracking semantics.
- The ThesisTrace Bounded Research Storage Spec remains
  authoritative for the one-MiB ResearchRun result boundary, retained
  Strategy series, transient calculation intermediates, columnar object
  encoding, Working Cache ownership, cleanup, and recovery.
- Hosted Platform V2 owns identity, Personal Workspace isolation, hosted
  admission, durable orchestration, deployment, and operations. These
  responsibilities must not duplicate or reinterpret quantitative contracts
  from the other two specs.
- ADR-0141, ADR-0143, and ADR-0145 record the aligned private-Storage and
  bounded-P3-progress decisions. ADRs remain the record of individual
  decisions; this specification is the complete feature acceptance boundary.
- Implementation work should be split into individually reviewable issues only
  after this specification and its dependent storage specification are both
  accepted. Each issue must preserve the three agreed test seams instead of
  replacing them with isolated mock-only tests.
