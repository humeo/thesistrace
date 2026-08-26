# Research Agent MCP Server

Status: ready-for-agent

## Problem Statement

ThesisTrace already has authoritative Core modules for ResearchRun, Research Batch, DailyTrack, Data Overview, Research Folder, Alpha authoring, execution, cancellation, retry, Stop, and result inspection. Today those capabilities are exposed primarily through the product UI and HTTP routes. An external Agent such as Codex has no small, stable, protocol-native surface through which it can discover safe research capabilities, submit fully specified work, poll durable state, and inspect bounded semantic results.

Exposing the existing HTTP API directly would leak transport-oriented shapes, invite a second implementation of domain rules, and make authorization, idempotency, dangerous-action handling, pagination, errors, and output bounds inconsistent. Moving domain behavior into a Cloudflare Worker would create a second authority outside Core. A broad MCP mirror would also expose Data Operator operations, storage internals, generic execution primitives, and destructive product actions that a Research Agent does not need.

The product therefore needs one native Core MCP adapter that presents a deliberately smaller Research Agent contract. It must work locally over stdio for Codex development and over stateless Streamable HTTP for a future remote deployment. Both transports must invoke the same request-local capability registry and the current Core module interfaces, preserve PostgreSQL Product State as the only business authority, and fail closed when authentication or authorization is missing.

The first delivery is successful when Codex can complete a real Fixture-backed research loop through stdio, the same contract passes deterministic Streamable HTTP integration tests with a local OAuth issuer, and all effectful calls remain idempotent, resource-addressed, observable, bounded, and recoverable independently of the MCP connection.

## Solution

Add a native Python MCP adapter beside the existing HTTP and Worker adapters. The adapter does not call ThesisTrace HTTP routes and does not contain domain behavior. It translates MCP inputs and outputs at one Capability Registry seam, authenticates a Research Agent principal, intersects deployment policy with granted OAuth scopes, and delegates to existing or deliberately deepened Core module interfaces.

The server exposes exactly the following eighteen V1 Tools:

| Area | Tool | Required scope | MCP behavior hints |
| --- | --- | --- | --- |
| Context | `get_research_context` | `research:read` | read-only, idempotent, closed-world |
| Context | `get_alpha_catalog` | `research:read` | read-only, idempotent, closed-world |
| Context | `diagnose_alpha_formula` | `research:read` | read-only, idempotent, closed-world |
| ResearchRun | `list_research_runs` | `research:read` | read-only, idempotent, closed-world |
| ResearchRun | `get_research_run` | `research:read` | read-only, idempotent, closed-world |
| ResearchRun | `get_research_run_result` | `research:read` | read-only, idempotent, closed-world |
| ResearchRun | `submit_research_run` | `research:execute` | effectful, idempotent by `request_id`, non-destructive, closed-world |
| ResearchRun | `cancel_research_run` | `research:cancel` | effectful, idempotent by `request_id`, destructive, closed-world |
| Research Batch | `list_research_batches` | `research:read` | read-only, idempotent, closed-world |
| Research Batch | `get_research_batch` | `research:read` | read-only, idempotent, closed-world |
| Research Batch | `submit_research_batch` | `research:execute` | effectful, idempotent by `request_id`, non-destructive, closed-world |
| Research Batch | `cancel_research_batch` | `research:cancel` | effectful, idempotent by `request_id`, destructive, closed-world |
| DailyTrack | `list_daily_tracks` | `tracking:read` | read-only, idempotent, closed-world |
| DailyTrack | `get_daily_track` | `tracking:read` | read-only, idempotent, closed-world |
| DailyTrack | `get_daily_track_result` | `tracking:read` | read-only, idempotent, closed-world |
| DailyTrack | `start_daily_track` | `tracking:execute` | effectful, idempotent by `request_id`, non-destructive, closed-world |
| DailyTrack | `retry_daily_track` | `tracking:execute` | effectful, idempotent by `request_id`, non-destructive, closed-world |
| DailyTrack | `stop_daily_track` | `tracking:stop` | effectful, idempotent by `request_id`, destructive, closed-world |

V1 uses Tools only. It does not expose MCP Prompts, Resources, Sampling, Elicitation, Subscriptions, generic execution tools, or aliases. The HTTP surface is one `/mcp` endpoint using stateless Streamable HTTP. The local surface is one stdio entrypoint. There is no legacy SSE endpoint, versioned endpoint, custom tool-set header, compatibility dispatcher, or transport-owned task state.

The six authorization scopes are exactly `research:read`, `research:execute`, `research:cancel`, `tracking:read`, `tracking:execute`, and `tracking:stop`. Research Batch uses the Research scopes. Local stdio uses a fixed `local_operator` principal with read and execute scopes by default; cancel and Stop scopes require explicit operator configuration. HTTP uses OAuth 2.1 protected-resource semantics. The deterministic test adapter verifies short-lived tokens from a local issuer. A production HTTP adapter must bind a real verifier and must fail startup if that verifier is absent. Invalid authentication never becomes anonymous access.

All effectful Tools require a caller-stable `request_id`. The authoritative module action stores or reuses the durable action receipt. Repeating the same `request_id` with the same canonical command fingerprint returns the original outcome and resource identifier. Reusing it with different inputs returns `IDEMPOTENCY_CONFLICT`. A JSON-RPC request identifier is transport correlation only and never substitutes for product idempotency.

Effectful work is asynchronous. Accepted calls return the durable `run_id`, `batch_id`, or `track_id`; status reads return `retry_after_seconds` while polling remains useful. Disconnecting or restarting either MCP transport does not cancel, lose, or own the work. The Agent resumes from the durable identifier.

Lists use stable opaque cursor pagination, descending creation order with a deterministic identifier tie-break, default limit 20, maximum limit 50, and `next_cursor`. Time-series observations use ascending session order. Position pages use a deterministic instrument order. The adapter must call a genuinely paginated module interface; it must not load an unbounded collection and slice it in memory.

Compact detail Tools return authorable input, lifecycle state, progress, timing, admissibility or failure summary, key metrics, and the available result sections. Result Tools return one semantic section at a time. ResearchRun result sections are `factor`, `strategy_summary`, `strategy_observations`, `terminal_strategy_state`, `terminal_positions`, and `provenance`. DailyTrack result sections are `factor`, `strategy_summary`, `strategy_observations`, `origin`, and `provenance`. Collection sections accept cursor and limit. The contract exposes product-visible formula, hypothesis, Factor horizons, benchmark comparison, daily observations, terminal state, positions, and provenance, but never Result Bundle manifests, RustFS object keys, private checkpoints, attempts, leases, recovery state, SQL, paths, or string-encoded internal JSON.

Correctable Formula Diagnostics and admission rejection are successful structured Tool outcomes. An admission response is a discriminated `accepted` or `rejected` value; a rejection contains stable issue codes, field or source ranges where applicable, and actionable messages. Missing resources, forbidden authority, lifecycle conflicts, idempotency conflicts, transient dependency failures, malformed Tool input, and unexpected failures are structured Tool errors with stable codes such as `NOT_FOUND`, `FORBIDDEN`, `STATE_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `TEMPORARILY_UNAVAILABLE`, `INVALID_INPUT`, and `INTERNAL`. Transient errors identify themselves as retryable and include bounded retry guidance. Internal failures are sanitized.

Every response uses MCP structured content with an explicit output schema. Request size, response size, call rate, per-principal concurrency, pagination, batch cardinality, formula size, and result-page bounds are fixed server constants. Existing Core admission and lifecycle constraints remain authoritative. The final numeric ingress constants are selected from deterministic tests and benchmarks and are not user-configurable in V1.

## User Stories

1. As a person using Codex to operate a local ThesisTrace installation, I want Codex to discover a small research-specific Tool inventory so that it can act without learning internal HTTP routes or storage details.
2. As that person, I want one Codex instruction to drive context discovery, Formula diagnosis, research submission, polling, and result inspection so that the Agent can complete a useful research loop end to end.
3. As that person, I want work accepted by the Agent to continue after the MCP connection closes so that a terminal restart does not lose a long-running ResearchRun, Research Batch, or DailyTrack action.
4. As that person, I want the Agent to resume polling from a durable identifier so that reconnection never depends on an MCP session object.
5. As a local operator, I want stdio to use a fixed `local_operator` principal so that development needs no product User table or interactive login flow.
6. As a local operator, I want the default stdio principal to omit cancel and Stop scopes so that an ordinary development connection cannot perform dangerous actions accidentally.
7. As a local operator testing dangerous behavior, I want cancel and Stop scopes to require explicit startup configuration so that enabling them is visible and intentional.
8. As a future remote operator, I want one OAuth-protected `/mcp` endpoint so that authentication, authorization, rate limits, and forwarding can be applied without duplicating domain APIs.
9. As a future remote operator, I want server startup to fail when the production token verifier is missing so that a deployment cannot silently expose anonymous or weakly authenticated Tools.
10. As a Research Agent, I want `get_research_context` to return the current Data Overview, readable Research Folders, supported research kinds, universes, neutralization modes, Strategy bounds, batch bounds, and other authoring constraints so that I can compose valid work before submitting it.
11. As a Research Agent, I want `get_research_context` to describe only the current usable data state and not let me enumerate or select Data Generations so that I cannot bypass the product's current-head rules.
12. As a Research Agent, I want Research Folders included as read-only context so that I can choose a valid destination without receiving Folder mutation authority.
13. As a Research Agent, I want `get_alpha_catalog` to return the authorable fields and builtins with their signatures, types, and concise descriptions so that I can build valid Formula expressions from the same catalog as the product.
14. As a Research Agent, I want `get_alpha_catalog` to optionally filter by a bounded list of identifiers so that I can refresh only the definitions relevant to a correction without repeatedly receiving the full catalog.
15. As a Research Agent, I want `diagnose_alpha_formula` to validate a Formula without creating a ResearchRun so that I can cheaply fix syntax, unknown identifiers, type errors, and source-ranged authoring problems.
16. As a Research Agent, I want Formula Diagnostics to be returned as structured `valid` and diagnostic values rather than an opaque protocol failure so that I can revise the Formula deterministically.
17. As a Research Agent, I want `list_research_runs` to page stable compact summaries and optionally narrow by Folder or research kind so that I can locate recent work without loading full Results.
18. As a Research Agent, I want `get_research_run` to return the frozen authorable input, lifecycle state, progress, timestamps, key metrics, and available result sections so that I can decide whether to poll, inspect, cancel, or report the outcome.
19. As a Research Agent, I want `submit_research_run` to accept a complete Factor Evaluation or Strategy Backtest snapshot so that no mutable browser draft or server-side conversational state is required.
20. As a Research Agent, I want common ResearchRun input to include `request_id`, `folder_id`, optional `name`, `formula`, optional `hypothesis`, `start_date`, `end_date`, `universe`, `neutralization`, and `research_kind` so that the command mirrors the current authoring contract.
21. As a Research Agent, I want a Strategy Backtest command additionally to require `holdings_count` from 1 through 100 and `rebalance_every_sessions` from 1 through 20 so that Strategy-specific constraints are explicit in the input schema.
22. As a Research Agent, I want `submit_research_run` to return either an accepted durable `run_id` or a structured correctable rejection so that I can distinguish invalid research from infrastructure failure.
23. As a Research Agent, I want accepted ResearchRuns to include a recommended polling delay so that I do not hammer Core while waiting for queued or running work.
24. As a Research Agent with `research:cancel`, I want `cancel_research_run` to address one `run_id` and require a stable `request_id` so that cancellation is explicit, auditable, and replay-safe.
25. As a person using a Host that displays dangerous-action confirmation, I want `cancel_research_run` marked destructive so that Codex can ask me before invoking it.
26. As a server operator, I want cancellation authority checked independently of the Host's confirmation UI so that a misleading annotation or nonconforming Host never becomes authorization.
27. As a Research Agent, I want `get_research_run_result` to retrieve one named semantic section at a time so that large Strategy outputs remain bounded and easy to reason about.
28. As a Research Agent, I want Factor result sections to include the product-visible horizon metrics and provenance so that I can assess the Factor without reading internal artifact files.
29. As a Research Agent, I want Strategy summary sections to include the same product-visible headline metrics and benchmark comparison as the product so that my conclusions use the authoritative interpretation.
30. As a Research Agent, I want Strategy observations paged in ascending session order so that I can analyze a long daily series without receiving a single oversized response.
31. As a Research Agent, I want terminal Strategy state and terminal positions available as separate bounded sections so that position cardinality cannot inflate every detail response.
32. As a Research Agent, I want stable cursors with no duplicates or gaps while paging an immutable Result so that I can reconstruct the complete semantic series reliably.
33. As a Research Agent, I want `list_research_batches` and `get_research_batch` to expose ordered item summaries, aggregate progress, lifecycle state, and durable child ResearchRun identifiers so that I can monitor batch work without a fabricated Batch Result.
34. As a Research Agent, I want `submit_research_batch` to accept exactly one `factor_evaluation` or `strategy_sweep` discriminated command so that incompatible batch shapes cannot be mixed.
35. As a Research Agent, I want a Factor Evaluation batch to accept 1 through 20 factors, each with a caller-stable `item_key`, optional `name`, `formula`, and optional `hypothesis`, plus shared date, universe, and neutralization inputs so that comparable work is admitted atomically.
36. As a Research Agent, I want a Strategy Sweep batch to accept one shared Alpha and 1 through 20 Strategy configurations, each with a caller-stable `item_key`, optional `name`, holdings count, and rebalance interval, so that the sweep represents one deliberate comparison matrix.
37. As a Research Agent, I want `submit_research_batch` to return one durable `batch_id` and either accepted or structured rejected status so that partial protocol success cannot be confused with accepted domain work.
38. As a Research Agent, I want to inspect each Batch item through its ResearchRun rather than through a duplicate Batch-level Result API so that there is one authoritative result contract.
39. As a Research Agent with `research:cancel`, I want `cancel_research_batch` to cancel the addressed Batch according to current Core lifecycle rules and return replay-safe action state so that repeated calls do not create conflicting outcomes.
40. As a person using Codex, I want Batch cancellation marked destructive so that the Host can request my confirmation before calling it.
41. As a Research Agent, I want `list_daily_tracks` to page stable compact summaries so that an installation with growing stopped history never returns an unbounded collection.
42. As a Research Agent, I want `get_daily_track` to expose origin ResearchRun, lifecycle state, current progress, block reason, retry eligibility, Stop eligibility, timing, and available result sections so that I can choose the next legal action.
43. As a Research Agent, I want `start_daily_track` to accept only a succeeded Strategy Backtest `run_id` and a stable `request_id` so that tracking always starts from an authoritative Strategy result.
44. As a Research Agent, I want Core to enforce one DailyTrack per origin ResearchRun and at most ten non-stopped DailyTracks so that Agent access cannot bypass current product invariants.
45. As a Research Agent, I want an invalid start to be returned as a structured admission rejection or lifecycle conflict with an actionable reason so that I do not repeatedly retry an impossible command.
46. As a Research Agent, I want `retry_daily_track` to be legal only for a blocked DailyTrack so that retry cannot be used as an alternate start, resume, or hidden state transition.
47. As a Research Agent, I want `retry_daily_track` to return the same durable `track_id`, replay-safe action outcome, and polling guidance so that retry does not create a second tracking identity.
48. As a Research Agent with `tracking:stop`, I want `stop_daily_track` to be legal only for active or blocked tracking and to be irreversible so that Stop has one unambiguous domain meaning.
49. As a person using Codex, I want `stop_daily_track` marked destructive so that the Host can ask for confirmation while the server still enforces the separate `tracking:stop` scope.
50. As a Research Agent, I want `get_daily_track_result` to expose bounded Factor, Strategy summary, daily observation, origin, and provenance sections so that I can inspect current tracking output without accessing checkpoints or storage objects.
51. As a Research Agent, I want every list and collection section to default to 20 items and reject limits above 50 so that response size remains predictable.
52. As a Research Agent, I want every cursor to be opaque and validated so that I cannot depend on or manipulate database ordering internals.
53. As a Research Agent, I want missing IDs, missing scopes, illegal lifecycle actions, reused conflicting request IDs, transient failures, invalid input, and internal failures to have distinct stable error codes so that recovery behavior does not depend on parsing prose.
54. As a Research Agent, I want transient failures to declare `retryable: true` and provide bounded retry guidance so that I can distinguish backoff from input correction.
55. As a Research Agent, I want internal errors sanitized so that SQL, filesystem paths, stack traces, credentials, and nested string-encoded JSON are never exposed as model context.
56. As a Research Agent, I want output schemas and structured content for every Tool so that the Host can validate results and the model can reason over stable fields rather than free-form text.
57. As a Research Agent, I want the Tool inventory filtered to the intersection of deployment allowlist and granted scopes so that unavailable dangerous actions are absent from discovery, not merely rejected after selection.
58. As a security reviewer, I want every Tool call to recheck its required scope and resource state so that cached discovery results cannot bypass current authorization or lifecycle rules.
59. As a security reviewer, I want no confirmation token accepted as proof that a human approved an action so that the server does not invent a non-portable trust signal.
60. As a security reviewer, I want no generic SQL, Python, shell, HTTP, object-store, or arbitrary API Tool so that Research Agent access cannot become remote code execution or an internal-network proxy.
61. As a Data Operator, I want all bootstrap, refresh, publication, garbage collection, Dataset Release, Data Generation selection, attempt, lease, checkpoint, and physical artifact operations absent from MCP so that Research Agent authority cannot cross the data-administration boundary.
62. As a product maintainer, I want both transports to invoke one Capability Registry and the same Core modules so that behavior cannot drift between stdio, Streamable HTTP, and the product API.
63. As a product maintainer, I want the HTTP MCP application to share the parent Core runtime lifespan correctly so that it does not open a second database, storage, or module authority.
64. As a product maintainer, I want the official Python MCP SDK used and pinned to a bounded stable major line so that protocol framing, structured outputs, transports, and authentication interfaces are not reimplemented locally.
65. As a product maintainer, I want a hard-cut V1 Tool contract with no aliases, legacy fields, fallback dispatcher, versioned endpoint, or obsolete SSE transport so that one current contract is easy to test and document.
66. As a product maintainer, I want MCP to add no permanent audit-log table so that structured operational telemetry stays diagnostic and PostgreSQL Product State remains authoritative.
67. As an operator, I want one structured operational event per Tool call containing subject, transport, Tool name, resource identifier when known, request identifier when supplied, outcome or stable error code, latency, response bytes, and trace identifier so that production failures can be correlated.
68. As an operator, I want tokens, Formula text, hypotheses, full arguments, full Results, and positions excluded from operational logs so that observability does not create a second sensitive data store.
69. As an operator, I want fixed request-byte, response-byte, rate, concurrency, batch, Formula, and page limits enforced before expensive work so that one Agent cannot exhaust Core resources.
70. As an operator, I want those ingress limits independent of product Users, credits, billing, and Campaign concepts so that a single-installation MCP server does not introduce an unneeded SaaS model.
71. As a test author, I want the same effectful `request_id` replayed concurrently and after process restart to return one original durable resource so that retries cannot duplicate research or tracking work.
72. As a test author, I want a reused `request_id` with a changed canonical fingerprint to return `IDEMPOTENCY_CONFLICT` so that accidental key reuse is visible and safe.
73. As a test author, I want deterministic local OAuth tokens with expiry, audience, scope, and invalid-signature cases so that HTTP authentication is tested without public network access or a real User account.
74. As a test author, I want Fake Model trajectories to cover discovery, context gathering, Formula correction, submission, polling, result paging, authorization denial, idempotent retry, transient backoff, cancellation, retry, and Stop so that Agent control flow is repeatable without asserting model wording.
75. As an acceptance tester, I want a real Codex stdio session against Fixture data to complete a research loop so that the first supported Host is proven through its actual integration surface.
76. As an acceptance tester, I want deterministic Streamable HTTP integration against the same Tool schemas and a local OAuth issuer so that the remote contract is proven before any Cloudflare deployment.
77. As a release operator, I want the final production image smoke to verify startup, health, MCP route construction with explicit test auth, Tool discovery, one read flow, one effectful flow, and the installed stdio entrypoint so that source-only success cannot mask packaging defects.
78. As a release operator, I want failed MCP tests to retain trace IDs, sanitized request and response envelopes, process exit codes, dependency state, logs, random seed, and image version so that failures are diagnosable without rerunning blindly.

## Implementation Decisions

### Architecture and ownership

- Implement one request-local Research Agent Capability Registry as the sole MCP-facing application seam. It owns Tool metadata, input and output schemas, scope requirements, authorization checks, error mapping, response bounds, and delegation to module interfaces. It owns no business lifecycle rules.
- Implement stdio and Streamable HTTP as thin protocol adapters around that registry. Neither adapter calls the other, calls product HTTP routes, or accesses repositories and object storage directly.
- Mount the Streamable HTTP application into the existing Core ASGI process and explicitly enter the MCP session manager from the parent lifespan, because a mounted ASGI application's lifespan is not assumed to run independently.
- Use stateless Streamable HTTP at the single `/mcp` route. Do not implement the obsolete HTTP-plus-SSE transport, transport sessions that own tasks, or a second domain server.
- Use the official Python MCP SDK for protocol framing, Tool registration, explicit structured output schemas, stdio, Streamable HTTP, and OAuth verification integration. Pin a bounded stable major line through the existing Python dependency workflow; do not implement MCP JSON-RPC or OAuth protocol machinery by hand.
- A future Cloudflare Worker may authenticate, rate-limit, protect against abuse, and forward to Core. It must not interpret ThesisTrace domain commands, execute research, persist business task state, or replace the Core authorization seam.

### Capability contract

- Publish exactly the eighteen Tools listed in this spec. V1 has no MCP Prompts, Resources, Sampling, Elicitation, Subscriptions, Tool aliases, compatibility fields, custom dispatcher, generic execution primitive, or Data Operator capability.
- Tool descriptions must state the legal lifecycle preconditions, material side effects, expected polling behavior, scope, and whether a correctable rejection is possible. MCP annotations are discoverability and Host-UX hints only.
- Mark reads as read-only and idempotent. Mark all effectful Tools idempotent because their product action is keyed by `request_id`. Mark only ResearchRun cancellation, Research Batch cancellation, and DailyTrack Stop as destructive. Mark every Tool closed-world because it acts only on the controlled ThesisTrace installation.
- Represent identifiers and cursors as opaque strings. Validate length and format at the boundary, but do not expose database keys, cursor composition, storage keys, paths, or internal enum variants not present in the product contract.
- `get_research_context` composes the current Data Overview, current readable Research Folders, and current authoring constraints from their module interfaces. It exposes no Data Generation listing or selector.
- `get_alpha_catalog` returns the current authorable field and builtin definitions. It accepts an optional bounded identifier list and returns explicit unknown-identifier entries rather than silently dropping requests.
- `diagnose_alpha_formula` accepts Formula text and returns a discriminated valid or invalid diagnostic result with stable diagnostic codes and source ranges.
- ResearchRun submission uses the current discriminated Factor Evaluation and Strategy Backtest contracts. The server does not infer missing research intent from prose and does not preserve a conversational draft.
- Research Batch submission uses the current discriminated Factor Evaluation and Strategy Sweep contracts, caller-stable item keys, and a hard cardinality of 1 through 20 items. Batch has no synthetic Result; item Results are read from child ResearchRuns.
- DailyTrack start, retry, and Stop delegate to current module invariants: start from one succeeded Strategy Backtest, one track per origin run, at most ten non-stopped tracks, retry only while blocked, and irreversible Stop only while active or blocked.

### Inputs, idempotency, and polling

- Every effectful input includes a non-empty caller-stable `request_id` with a fixed maximum length. Canonicalize the domain command, not the transport envelope, before computing the idempotency fingerprint.
- Reuse existing durable command receipts and Product State wherever current module actions already provide idempotency. If an action lacks durable fingerprint comparison, deepen that domain action rather than adding an MCP-local cache. No in-memory idempotency store is acceptable.
- Same identifier and same fingerprint replays the original accepted, rejected, or completed action outcome. Same identifier and different fingerprint returns `IDEMPOTENCY_CONFLICT`. Concurrent duplicate admission produces one durable resource.
- Submission and action Tools never wait for Worker completion. They return a durable resource identifier, current state, replay indicator, and bounded `retry_after_seconds` guidance when polling is useful.
- Compact get responses enumerate available result sections only after those sections are authoritatively readable. They never return a temporary storage pointer for the Agent to dereference.

### Pagination and result views

- All history lists use seek-based, stable opaque cursors, descending creation time, a deterministic identifier tie-break, default limit 20, and maximum limit 50.
- Deepen DailyTrack listing to a paginated module interface. Do not fetch all tracks and slice inside the MCP adapter.
- Immutable observation pages use ascending session order. Position pages use deterministic instrument order. Cursor validation rejects a cursor used with an incompatible resource, section, filter, or ordering.
- `get_research_run_result` accepts `run_id`, one section from the declared ResearchRun section set, and cursor/limit only for collection sections.
- `get_daily_track_result` accepts `track_id`, one section from the declared DailyTrack section set, and cursor/limit only for collection sections.
- Return product-semantic values, units, date/session labels, benchmark identity, missing-value semantics, and provenance required to interpret the Result. Exclude manifests, raw partition layout, object keys, attempts, checkpoints, leases, recovery data, and unpublished intermediate state.
- Enforce a hard response-byte ceiling after schema serialization. If one legal item cannot fit, return a stable internal contract failure rather than truncate JSON or silently omit fields.

### Authentication and authorization

- Define one authenticated Research Agent principal passed request-locally to the Capability Registry. Do not use global mutable principal state.
- Local stdio binds `local_operator` and grants `research:read`, `research:execute`, `tracking:read`, and `tracking:execute` by default. `research:cancel` and `tracking:stop` are absent unless an operator explicitly enables them for that process.
- Deterministic HTTP tests use a local OAuth issuer and short-lived signed bearer tokens. Test cases cover issuer, audience, expiry, not-before time, signature, malformed tokens, scopes, and grant revocation behavior without public network access.
- Production HTTP uses a real OAuth verifier/provider chosen at deployment time. If HTTP MCP is enabled in production and the verifier is not configured, application construction fails. There is no `AUTH_DISABLED`, anonymous mode, failed-token downgrade, query-token path, or trusted custom scope header.
- The visible Tool inventory is the intersection of the deployment allowlist and the authenticated grant. Every Tool invocation repeats scope and resource authorization checks to handle stale Host discovery caches.
- Host confirmation is a client UX concern. The server does not accept a confirmation token and does not treat `destructiveHint` as proof. It authorizes only from the authenticated principal, scope, resource state, idempotency, and current Core invariants.

### Errors and structured outcomes

- Use explicit structured output schemas for all Tools. Do not put the only machine-readable payload in free-form `content` text.
- Return Formula Diagnostics and domain admission rejection as successful discriminated outcomes because the Agent can correct and resubmit them.
- Map boundary input violations to `INVALID_INPUT`; missing resources to `NOT_FOUND`; insufficient scope or resource authority to `FORBIDDEN`; illegal lifecycle transitions to `STATE_CONFLICT`; changed commands under one request identifier to `IDEMPOTENCY_CONFLICT`; bounded transient dependency failures to `TEMPORARILY_UNAVAILABLE`; and sanitized unexpected failures to `INTERNAL`.
- Structured errors include stable code, concise message, `retryable`, optional bounded retry delay, trace identifier, and safe field or resource context. They never contain SQL, credentials, token claims beyond safe subject identity, stack traces, filesystem paths, object keys, Formula or hypothesis text, or string-encoded nested JSON.
- Do not transform an internal exception into a successful empty result. Do not convert authorization denial into not-found unless an existing resource-hiding policy explicitly requires it.

### Ingress protection and observability

- Select fixed request-byte, response-byte, per-principal rate, per-principal concurrent-call, Formula-size, and collection bounds from deterministic load tests and the current production resource envelope. Keep them server-owned and non-configurable in V1.
- Apply cheap authentication, schema, size, scope, and concurrency checks before database or object-store work. Core admission remains authoritative for business capacity and lifecycle constraints.
- Emit one structured completion event for each Tool call with authenticated subject, transport, Tool name, resource identifier when known, request identifier when supplied, outcome or error code, latency milliseconds, response bytes, and trace identifier.
- Never log bearer tokens, raw token claims, Formula text, hypothesis text, full Tool arguments, full Results, observations, terminal positions, storage locations, or credentials. Add canary tests that fail if these values enter logs.
- Operational events are disposable diagnostics only. Do not add an MCP audit table or reconstruct Product State from logs.

### Schema and deployment impact

- No MCP-specific User, Workspace, tenant, session, Campaign, quota, billing, Tool grant, result cache, or audit schema is introduced.
- No MCP-specific task or idempotency table is introduced. Any required durable idempotency strengthening belongs to the existing authoritative domain action and its Product State schema, with the smallest forward-only schema change needed for that action.
- Result pagination should use existing immutable result representations and repository queries. Add only the index or query support proven necessary by an integration test or benchmark; do not denormalize Results for MCP.
- Add the MCP SDK as a bounded Python dependency and expose a packaged stdio entrypoint. The production image must contain the same code and dependency versions used by tests.
- Do not enable a public Cloudflare deployment in the first delivery. The remote HTTP adapter and OAuth protected-resource contract are permanent production architecture, but the first gate uses the deterministic local issuer.

## Testing Decisions

- The primary test seam is the Capability Registry invoked through its public module interface with a real Core runtime. Exercise Tool discovery, authorization, schemas, delegation, structured outcomes, and error mapping at this seam; do not unit-test private handler functions or assert implementation call counts.
- Keep transport tests thin but real. Run protocol-level stdio tests through the packaged process and Streamable HTTP tests through the mounted ASGI application, including initialization, Tool discovery, Tool invocation, malformed JSON-RPC, disconnect, reconnect, and graceful shutdown.
- Use real isolated PostgreSQL, RustFS, queue, and Worker dependencies for ResearchRun, Research Batch, DailyTrack, idempotency, cancellation, retry, Stop, result publication, and recovery tests. Do not mock owned infrastructure.
- Give each integration run its own isolated environment, database, storage, network, deterministic clock, UUID source, random seed, and Fixture data. Use bounded condition polling; never use arbitrary sleeps or the public internet.
- Add an exact contract inventory test asserting all eighteen Tool names, six scopes, descriptions, annotations, input schemas, output schemas, and scope-filtered visibility. Assert that aliases, Data Operator Tools, generic execution Tools, Prompts, Resources, Sampling, Elicitation, Subscriptions, and legacy SSE routes are absent.
- Add schema tests for both ResearchRun variants, both Research Batch variants, every Batch cardinality boundary, universe and neutralization enums, Strategy bounds, date rules, item-key uniqueness, request-identifier bounds, cursor/limit rules, and section-specific result inputs.
- Add `get_research_context` contract tests proving that current Data Overview, Folders, and authoring constraints are composed correctly while Data Generation selection and Folder mutation affordances are absent.
- Add Alpha Catalog tests for complete output, bounded identifier filtering, unknown identifiers, deterministic ordering, response-size bounds, and consistency with Formula Diagnostics.
- Add Formula Diagnostics tests for valid Formula, parse failure, unknown identifiers, type mismatch, forbidden constructs, expression-size boundary, multiple diagnostics, Unicode source ranges, and sanitized unexpected failures.
- Add ResearchRun acceptance tests for accepted Factor Evaluation, accepted Strategy Backtest, correctable rejection, queued/running/succeeded/failed state, durable polling guidance, cancellation in every legal and illegal state, duplicate admission, concurrent duplicate admission, conflicting fingerprint, process restart, and result publication.
- Add Research Batch acceptance tests for both kinds, atomic admission, 1-item and 20-item boundaries, zero and 21 rejection, duplicate item keys, ordered item summaries, partial child completion, Batch cancellation, duplicate action replay, process restart, and child Result access through ResearchRun Tools.
- Add DailyTrack acceptance tests for valid start, non-Strategy origin rejection, unsucceeded origin rejection, one-track-per-run, ten-active capacity, concurrent capacity race, blocked retry, retry in illegal states, active Stop, blocked Stop, Stop in illegal states, irreversible Stop, duplicate and conflicting action identifiers, restart, and current result publication.
- Add pagination tests with more than 50 runs, batches, tracks, observations, and positions. Assert stable order, opaque cursors, exact boundaries, no duplicates, no gaps, correct `next_cursor`, cursor/filter binding, cursor/resource binding, immutable replay, and rejection of oversized limits.
- Add result-contract tests for every ResearchRun and DailyTrack section, Factor horizons, Strategy summary and benchmark, daily observations, terminal state, positions, origin, provenance, missing values, units, finite-value rules, oversized responses, and absence of manifests, object keys, checkpoints, attempts, SQL, and filesystem paths.
- Add authorization tests for default local safe scopes, explicitly enabled local dangerous scopes, every individual OAuth scope, deployment-allowlist intersection, stale discovery followed by denied invocation, invalid signature, wrong issuer, wrong audience, expired and not-yet-valid tokens, malformed bearer headers, absent tokens, and fail-closed production construction.
- Add dangerous-action tests proving destructive annotations exist, server authorization does not depend on Host confirmation, no confirmation token is accepted, and denied cancel or Stop cannot mutate Product State.
- Add idempotency tests at the authoritative module boundary and both transports. Same command and same `request_id` must replay the original accepted or rejected outcome before completion, after completion, concurrently, and after process restart. A changed command must return `IDEMPOTENCY_CONFLICT` without creating or mutating a resource.
- Add structured-error tests for `INVALID_INPUT`, `NOT_FOUND`, `FORBIDDEN`, `STATE_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `TEMPORARILY_UNAVAILABLE`, and `INTERNAL`, including retry guidance, trace identifiers, stable schemas, and safe context.
- Add redaction canaries containing recognizable token, Formula, hypothesis, path, SQL, credential, observation, and position values. Assert none appear in application logs, protocol errors, health responses, or operational events.
- Add ingress tests that prove request, response, rate, concurrency, Formula, batch, cursor, and page limits fail before expensive work. Benchmark the chosen constants against the production resource envelope and record the measured rationale alongside the implementation.
- Add deterministic Fake Model trajectory tests that assert task completion and artifacts rather than exact model prose. Cover discovery, context gathering, valid direct submission, diagnostic correction and resubmission, polling with delay, pagination, transient backoff, denied dangerous action, idempotent transport retry, Batch monitoring, DailyTrack start, blocked retry, and Stop.
- Add one real Codex acceptance flow over stdio with Fixture data. It must discover only the expected safe Tools, obtain context, diagnose or author a Formula, submit work, poll to completion, inspect bounded Result sections, and report the durable identifiers and findings. Codex is the only required real Host for V1.
- Add deterministic Streamable HTTP integration with the local OAuth issuer. It must verify protected-resource behavior, scope-filtered discovery, one read flow, one effectful flow, disconnect/reconnect polling, and the same structured schemas as stdio.
- Extend the final production image smoke to verify image startup, health, parent/MCP lifespan, explicit test OAuth construction, `/mcp` discovery, one read flow, one effectful flow, Worker completion, result read, and the packaged stdio entrypoint. The smoke uses isolated real dependencies and Fixture data.
- Integrate all new deterministic tests into the existing local reproducible test and release gates. A failure must preserve sanitized protocol envelopes, relevant service state, trace identifier, logs, exit code, random seed, and image version.

## Out of Scope

- A public Cloudflare Worker deployment, production OAuth provider selection, provider registration, domain routing, or Cloudflare account configuration.
- Any second real MCP Host beyond Codex in V1.
- Product User accounts, login UI, multi-tenancy, Workspace ownership, organization membership, per-user resource ownership, SaaS isolation, credits, billing, or plans.
- Agent Campaigns, autonomous research budgets, recursive task design, or server-side interpretation of how many follow-up experiments one natural-language instruction authorizes.
- Data Operator capabilities including bootstrap, refresh, Dataset Release creation, Data Generation selection, publication, inspection, correction, replay, and garbage collection.
- Folder creation, update, move, or deletion. V1 only reads current Folder choices through context.
- ResearchRun, Research Batch, DailyTrack, Result, or Folder deletion.
- ResearchRun retry as a public Agent Tool. The current eighteen-Tool contract exposes submission, cancellation, and inspection only.
- Batch-level Result objects or duplicate Batch result aggregation outside current item and child ResearchRun semantics.
- Raw Result Bundle manifests, object-store keys, downloadable internal artifacts, SQL, repository access, checkpoints, attempts, leases, Worker ownership, recovery internals, or unpublished intermediate outputs.
- Generic shell, Python, SQL, HTTP, browser, file, object-store, or arbitrary API execution Tools.
- MCP Prompts, Resources, Sampling, Elicitation, Subscriptions, server-initiated notifications, task ownership in protocol sessions, or long-held polling requests.
- Tool aliases, old field names, versioned endpoints, compatibility layers, migration adapters, fallback dispatchers, or legacy HTTP-plus-SSE transport.
- Configurable V1 Tool sets through request headers, alternate domain endpoints, or principal-supplied scope claims.
- A permanent MCP audit table, MCP result cache, MCP session database, MCP idempotency cache, or telemetry-driven business recovery.
- Changes to the economic meaning, calculation method, execution semantics, authoring language, or current lifecycle invariants of ResearchRun, Research Batch, or DailyTrack.
- Production rollout, DNS, WAF policy, global rate-limit tuning, or external penetration testing beyond the deterministic first-delivery contract.

## Further Notes

- This spec adopts the established pattern shared by mature remote MCP implementations: keep domain authority behind a narrow adapter, use OAuth scopes for capability grants, expose bounded task-oriented Tools, and keep durable work outside the protocol connection. The preceding Cloudflare and GitHub MCP reference research informed the shape but does not make either implementation a runtime dependency.
- The architecture decisions are recorded in ADR-0220 through ADR-0230. The current domain glossary defines Research Agent as an external actor and Research Agent Authority as a request-local grant; implementation must keep those meanings intact.
- The official Python MCP SDK should be rechecked at implementation time and pinned to the then-current stable major line. The design depends on supported stdio, Streamable HTTP, structured Tool output, ASGI mounting, and token verification interfaces, not on an unreleased SDK API.
- The confirmed testing seam is one Capability Registry/module interface backed by the real Core runtime, with protocol adapters tested separately and real Codex used only for the first Host acceptance. No further design interview is required before implementation.
- This is a feature spec only. It intentionally does not generate implementation tickets, preserve legacy contracts, or authorize production deployment.
