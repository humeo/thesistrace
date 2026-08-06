Status: ready-for-agent

# ThesisTrace Local Development Lifecycle

## Problem Statement

As the ThesisTrace maintainer, I need one predictable local lifecycle for
developing and testing the accepted Core product loop. The repository currently
uses a hybrid runtime: PostgreSQL and RustFS run in Docker Compose while the Web,
API, and Worker run directly on the host. Development and full tests also reuse
a fixed Compose project and data location, the complete gate is one long command
chain, cleanup is not guaranteed after failure, and API/Worker startup owns
database migration as a side effect.

This makes lifecycle boundaries ambiguous. A reset or failed test can affect
state outside the intended test run, the runtime topology differs depending on
the command used, and the slow complete gate is the only clearly documented
verification path. The project is currently in local development and local
testing only. It has no active Staging or Production environment and must not
acquire speculative release, deployment, backup, or production-secret machinery
as part of this work.

## Solution

Provide one Compose-defined topology for the Web, API, Worker, PostgreSQL,
RustFS, and a one-shot database migration service. Development and test use the
same stable service relationships with separate overlays, configuration, project
names, ports, and data lifecycles. Development preserves state until an explicit
safe reset. Every integration or browser test run receives an isolated,
disposable environment that cannot address development data.

Expose the lifecycle through a small set of pnpm commands. Keep fast Python and
TypeScript tests on the host under mise, Node.js 24, pnpm, and uv for short
feedback loops. Use host test runners against real disposable Compose services
for integration and browser acceptance. The complete local gate composes these
layers, captures evidence before cleanup on failure, and remains the merge
boundary for the current single-maintainer workflow.

## User Stories

1. As a maintainer, I want one documented local lifecycle, so that I do not have to infer which startup path is authoritative.
2. As a maintainer, I want pnpm to be the only lifecycle command interface, so that the project does not reintroduce Makefile entry points.
3. As a maintainer, I want mise to activate Node.js 24 and the pinned pnpm version, so that JavaScript tooling is reproducible when I enter the repository.
4. As a new contributor, I want one bootstrap command, so that I can install host dependencies and prepare development images without learning internal scripts.
5. As a developer, I want the Web, API, Worker, PostgreSQL, and RustFS to run through Compose, so that there is one local service topology.
6. As a developer, I want one foreground development command, so that I can see coordinated service logs while I work.
7. As a developer, I want one background development command that waits for health, so that other terminal work can begin only after the system is ready.
8. As a developer, I want stopping development to preserve data, so that ordinary shutdown does not erase my work.
9. As a developer, I want reset to be explicitly destructive, so that data loss never occurs as a side effect of startup or shutdown.
10. As a developer, I want reset restricted to the canonical development project, so that a malformed variable cannot delete unrelated Compose resources.
11. As a developer, I want development to start from an empty product state after reset, so that the first Data Update remains a real product action.
12. As a developer, I want no automatic Fixture publication during bootstrap or reset, so that lifecycle setup does not bypass the accepted Core interface.
13. As a developer, I want Web source changes synchronized into its container, so that Vite hot module replacement gives immediate browser feedback.
14. As a developer, I want API source changes synchronized and reloaded, so that backend edits do not require a full manual restart.
15. As a developer, I want Worker source changes synchronized and the Worker restarted, so that background behavior follows the current source.
16. As a developer, I want dependency-manifest changes to rebuild the affected image, so that container dependencies cannot silently lag behind lock files.
17. As a developer, I want container dependency directories isolated from host dependency directories, so that macOS and Linux packages do not overwrite each other.
18. As a developer, I want one logs command, so that I can inspect all services without reconstructing Compose arguments.
19. As a developer, I want stable local service addresses, so that the browser and host-side test runners can reach the intended environment.
20. As a developer, I want health checks on long-running services, so that a running container is not mistaken for a ready product.
21. As a developer, I want the API and Worker to start only after database migration succeeds, so that they never operate against a partially migrated schema.
22. As a maintainer, I want migration to run as a one-shot service, so that schema mutation is not hidden in every long-running process startup.
23. As a maintainer, I want API and Worker startup to verify rather than mutate the schema, so that lifecycle ownership remains explicit.
24. As a developer, I want committed example configuration for development and test, so that required non-secret settings are discoverable.
25. As a developer, I want every lifecycle command to select its configuration explicitly, so that implicit environment-file precedence does not change behavior.
26. As a maintainer, I want secrets excluded from committed development configuration, so that local convenience cannot leak credentials.
27. As a developer, I want the live Tushare credential probe to remain separate, so that ordinary local gates stay deterministic and offline from that provider.
28. As a developer, I want a fast test command on the host, so that normal edits receive feedback without starting the complete integration stack.
29. As a developer, I want the fast gate to include lint, type checking, pure Python tests, and Web unit tests, so that inexpensive regressions fail early.
30. As a developer, I want integration tests to create a fresh Compose project, so that they prove behavior against real PostgreSQL and RustFS without reusing development state.
31. As a developer, I want browser tests to create a complete fresh Compose project, so that the accepted Core journey is tested against the real local topology.
32. As a developer, I want each test project to have a unique identifier, so that concurrent or interrupted runs cannot share containers, networks, ports, or volumes.
33. As a developer, I want test services to receive isolated ports, so that tests cannot accidentally connect to development services.
34. As a developer, I want test data to begin empty, so that migration and fixture preparation are deterministic for every run.
35. As a developer, I want tests to prepare their own fixed data through their accepted seams, so that test fixtures never contaminate development.
36. As a developer, I want integration and browser runners to remain on the host, so that feedback stays faster than containerizing the test tools.
37. As a maintainer, I want host test versions constrained by mise, uv, and lock files, so that the speed choice remains reproducible.
38. As a developer, I want a complete check command, so that one local command proves every required test layer before merge.
39. As a developer, I want the complete check to run fast tests before expensive tests, so that obvious failures stop early.
40. As a developer, I want test cleanup registered before tests begin, so that a failing command cannot bypass teardown.
41. As a developer, I want successful test environments destroyed with their volumes, so that repeated runs do not accumulate stale state.
42. As a developer, I want failed test environments inspected before destruction, so that cleanup does not erase diagnostic evidence.
43. As a developer, I want Compose status, timestamped logs, and container inspection saved on failure, so that infrastructure failures can be diagnosed after teardown.
44. As a developer, I want Pytest reports and Playwright screenshots or recordings saved with the same run identity, so that application and infrastructure evidence can be correlated.
45. As a developer, I want failed-run artifacts stored outside Git tracking, so that diagnostics do not pollute commits.
46. As a developer, I want an explicit keep-environment switch, so that I can preserve a failing stack when interactive inspection is more useful than cleanup.
47. As a maintainer, I want the keep-environment switch disabled by default, so that unattended runs remain self-cleaning.
48. As a maintainer, I want test cleanup to reject the development project name, so that no test exit path can erase development data.
49. As a maintainer, I want lifecycle behavior tested through pnpm commands rather than private shell functions, so that tests cover the interface developers actually use.
50. As a maintainer, I want Compose configuration validated before services start, so that malformed overlays or unresolved variables fail before mutating local state.
51. As a maintainer, I want service images pinned rather than floating on latest tags, so that local behavior does not change unexpectedly.
52. As a maintainer, I want the existing real PostgreSQL and pinned RustFS acceptance retained, so that lifecycle simplification does not weaken product evidence.
53. As a maintainer, I want the accepted browser journey retained, so that the new topology still proves Data, Research Definition, ResearchRun, and DailyTrack behavior end to end.
54. As a maintainer, I want non-trivial lifecycle changes represented by Local Markdown Specs and Issues, so that implementation has explicit scope and acceptance.
55. As a maintainer, I want work performed on short-lived feature, fix, or chore branches, so that main stays locally verifiable.
56. As a maintainer, I want local code review and the complete check before fast-forwarding main, so that the current workflow has a meaningful merge gate without remote CI.
57. As a maintainer, I want small bounded fixes to avoid unnecessary full Specs, so that process cost stays proportional to risk.
58. As a maintainer, I want ADRs reserved for durable and surprising trade-offs, so that architecture history remains useful rather than noisy.
59. As a maintainer, I want lifecycle documentation to state that only Development and Test exist, so that local evidence cannot be described as production readiness.
60. As a maintainer, I want production-oriented artifacts omitted, so that the Core development loop is not blocked by speculative deployment work.

## Implementation Decisions

- The active lifecycle contains exactly two environments: a persistent local
  Development environment and an ephemeral local Test environment. Release is
  a future process, not an environment in this scope.
- A base Compose definition owns the stable service topology: Web, API, Worker,
  PostgreSQL, RustFS, and a one-shot migration service. Development and test
  overlays express lifecycle differences. Profiles are not used to represent
  environments.
- All product services run in Compose. pnpm remains the developer-facing
  orchestrator and delegates non-trivial Compose, safety, evidence, and cleanup
  logic to dedicated scripts.
- The command contract is `pnpm bootstrap`, `pnpm dev`, `pnpm dev:up`,
  `pnpm dev:stop`, `pnpm dev:reset`, `pnpm dev:logs`, `pnpm test`,
  `pnpm test:integration`, `pnpm test:e2e`, and `pnpm check`.
- Makefile is not part of the active lifecycle and must not be restored.
- Development uses one fixed canonical Compose project. Its ordinary stop path
  preserves state. Its reset path validates the exact project identity before
  deleting development volumes and bringing the empty environment back up.
- Test runs generate unique project and run identities. Test networks, ports,
  and volumes are isolated from Development and from other test runs.
- Destructive scripts accept only the canonical Development identity or the
  canonical Test prefix. Empty, unexpected, production-like, and unrelated
  project names are rejected before any destructive Compose operation.
- Compose Watch is the authoritative development synchronization mechanism.
  Source changes synchronize, API reloads, Worker changes restart the Worker,
  Web changes use Vite HMR, and dependency manifests trigger image rebuilds.
- Host and container dependency directories remain separate. Host dependencies
  support editors and fast test runners; container dependencies support the
  running application services.
- Backend and Web build stages may be separated according to their genuinely
  different Python and Node.js runtimes, while still participating in the same
  Compose topology and lifecycle.
- Database migration becomes one explicit one-shot service using the same
  backend code and dependency set as API and Worker. Long-running processes no
  longer mutate schema during ordinary startup and wait for successful
  migration before becoming ready.
- Development reset performs migration but no automatic data publication or
  Seed. The first Fixture-backed Dataset Release remains a user-visible Data
  Update through the accepted Web or HTTP interface.
- Test fixtures are private to each test run and are prepared through existing
  test and product seams. They never reuse or modify Development data.
- Long-running services define meaningful health checks. Lifecycle commands
  wait for health rather than treating container creation as readiness.
- Development and test configuration are explicit and separate. Committed
  examples contain only non-secret defaults. Commands select configuration
  explicitly instead of depending on an implicit environment file.
- Pinned mise tools, uv state, pnpm lock state, and pinned infrastructure images
  establish the current reproducibility boundary. Live Tushare remains a
  separate credential-dependent gate.
- Fast Python and TypeScript tests execute on the host. Integration and browser
  runners also execute on the host but address only their newly created Test
  Compose project. Containerized test runners and production-image smoke tests
  are deferred until image-release work exists.
- `pnpm test` is the fast feedback gate. The integration and browser commands
  own isolated environment setup, evidence capture, and teardown. `pnpm check`
  runs all layers in cost order and is the current local merge gate.
- Cleanup is installed with an exit trap before a Test environment is created.
  Success cleans immediately. Failure first captures Compose status,
  timestamped logs, container inspection, and available test reports, then
  cleans unless an explicit keep-environment switch is enabled.
- Failed-run evidence is grouped by run identity in ignored local state. The
  keep-environment switch is a diagnostic escape hatch, not the default.
- Non-trivial work follows Local Markdown Spec/Issue planning, a short-lived
  branch, vertical implementation, layered tests, complete local verification,
  local code review, and fast-forward merge. GitHub Pull Requests are not a
  required gate in the current local-only phase.
- The full-Compose Development/Test topology is a durable, non-obvious trade-off
  and should be recorded in an ADR. General lifecycle vocabulary does not
  belong in the product domain glossary.

## Testing Decisions

- Tests assert observable lifecycle behavior through the pnpm command surface,
  Compose service health, public HTTP behavior, and the real browser journey.
  They do not couple to private shell-function structure or incidental Compose
  container names beyond the documented safety identity contract.
- The highest acceptance seam is `pnpm check`. It must run the fast gate, the
  real PostgreSQL/RustFS integration gate, and the complete browser gate, and it
  must leave no Test environment behind after success.
- `pnpm test` verifies lint, type safety, pure Kernel and architecture behavior,
  adapter contracts, and Web unit behavior without creating an integration
  environment.
- `pnpm test:integration` proves that a unique empty Test environment validates
  Compose configuration, starts pinned PostgreSQL and RustFS, completes
  migration, reaches health, runs the existing integration and acceptance
  suites, captures failure evidence when needed, and cleans independently.
- `pnpm test:e2e` proves that a unique complete Test environment starts the Web,
  API, Worker, PostgreSQL, RustFS, and migration boundaries before the host
  Playwright runner drives the accepted Core product journey.
- Existing Core integration tests are the prior art for real PostgreSQL
  transactions, publication, restart, retries, and recovery. Existing browser
  acceptance is the prior art for the four-resource Data, Research Definition,
  ResearchRun, and DailyTrack journey.
- Safety tests exercise empty, malformed, Test, Development, and production-like
  project identities and prove that destructive commands reject every identity
  outside their explicit allowlist.
- Isolation tests run or simulate two unique Test identities and prove that
  their networks, ports, volumes, and data are not shared and that neither can
  address Development.
- Migration tests prove that the one-shot service completes before API/Worker
  readiness, that a migration failure blocks steady services, and that ordinary
  long-running startup does not mutate schema.
- Development lifecycle tests prove that stop preserves state, reset deletes
  only Development state, reset returns to the canonical empty product, and
  ordinary startup does not publish Fixture data.
- Watch behavior is accepted at the service boundary: relevant source changes
  update or restart the intended service, while dependency-manifest changes
  rebuild it and host dependency directories remain untouched.
- Failure-path tests intentionally fail after Test startup, confirm that status,
  logs, inspection, and reports are captured before teardown, and confirm that
  the explicit keep switch preserves only the intended Test environment.
- Documentation checks confirm that active instructions use mise, Node.js 24,
  pnpm, uv, and the new pnpm lifecycle commands and contain no active Makefile,
  Staging, Production, deployment, backup, or release instructions.
- Live Tushare access is excluded from every deterministic default gate. Its
  explicit credential probe remains separate and is not evidence of lifecycle
  acceptance.

## Out of Scope

- Staging or Production environments and production Compose overlays.
- Production Docker targets, immutable release images, registries, image
  digests, release manifests, tags, promotion, deployment, rollback, or Smoke
  Tests against a release image.
- GitHub Actions, mandatory GitHub Pull Requests, remote required checks, or
  environment approvals.
- Production domains, reverse proxies, TLS, authentication, tenancy, quotas,
  Secret managers, or production environment files.
- Production migration compatibility, deployment locks, Expand-Migrate-Contract
  release sequencing, backup, restore rehearsal, monitoring, or alerting.
- Automatic Development Seed data or a demonstration-environment seed command.
- Containerized host test runners; these may be reconsidered with the future
  immutable-image release phase.
- Changes to the accepted Data, Research Definition, ResearchRun, DailyTrack,
  Research Kernel, quantitative, publication, or immutable-result semantics.

## Further Notes

- This effort adapts the Compose-first lifecycle reference to ThesisTrace rather
  than copying its production stages. Development and Test are real current
  environments; Production is explicitly absent.
- The current repository already proves the product through real PostgreSQL,
  pinned RustFS, and desktop browser acceptance. The lifecycle migration must
  preserve or strengthen those seams, not replace them with mocks.
- The existing working tree contains lifecycle-tooling changes and unrelated
  untracked research material. Implementation must preserve unrelated work and
  stage only the intended lifecycle effort.
- The next workflow step is to convert this Spec into dependency-ordered Local
  Markdown implementation Issues. This Spec does not itself authorize or carry
  out implementation.
