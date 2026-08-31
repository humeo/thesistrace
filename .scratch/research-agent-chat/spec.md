# Built-in Research Agent Chat

Status: ready-for-agent

## Problem Statement

ThesisTrace can already author, diagnose, execute, monitor, and inspect quantitative
research through authoritative Core modules and the Research Agent MCP surface.
The product still requires a Researcher to translate an investment idea into a
Formula and operate the Research workspace manually. A Researcher who can describe
an idea in natural language has no first-party place to ask ThesisTrace to turn that
idea into one or more Alpha experiments, run them, and explain the result.

Putting a chat box inside the existing Research page would merge two different
products and lifecycles. Research is the authoritative workspace for explicit
Formula authoring and immutable ResearchRuns. Chat is a conversational workspace
whose Messages, generated Alpha Proposals, model choices, and Agent Runs may be
discarded without changing Research truth. A Chat Session may create several
ResearchRuns, and a ResearchRun must remain valid after the originating Chat Session
is deleted.

The browser also must not become the Agent runtime. It cannot safely hold provider
credentials, OAuth access tokens, model orchestration, long-running Tool loops, or
durable conversation state. FastAPI Core must not absorb those concerns either:
Core remains deterministic Research authority, while model choice, instructions,
Memory, Tool choice, and Agent Run behavior belong to an Agent framework.

ThesisTrace therefore needs one standalone, ChatGPT-like `/chat` product surface and
one private Agent Host. The browser uses CopilotKit React Core as a headless chat
client, AG-UI for Agent event streaming, and A2UI for validated generative UI. The
Agent Host combines CopilotKit Runtime with one Mastra Research Agent. That Agent is
the selected registered model and reasoning effort, Mastra `instructions`, current
Chat Session Memory, and the Tools dynamically discovered from the authenticated
Core `/mcp` endpoint. ThesisTrace does not maintain a second Tool inventory or a
parallel workflow engine around it.

The feature is successful when a logged-in Researcher can open a dedicated Chat
page, describe an Alpha idea in text, watch the Agent call the currently authorized
MCP Tools, receive a streamed explanation and structured Alpha or Result UI, return
to the durable Chat Session later, and navigate to any resulting Research object;
deleting that Chat Session must delete only Chat state. The final production images
must prove this loop through Caddy with real owned infrastructure and a deterministic
Scripted Fake Model, while real-model quality remains a separate Eval.

## Solution

Add Chat as a first-class application destination rather than a mode of Research.
The Chat page uses a persistent session sidebar, a focused conversation canvas, and
a bottom composer. Workspace links appear near the top of the sidebar, before Chat
history. The session list is Researcher-owned, durable, grouped by recency, and
supports New Chat, rename, selection, and deletion. An empty New Chat is browser
state only; the first submitted message creates the durable Mastra Thread and then
the model generates its initial title.

Use the following runtime boundary:

```text
Browser
  -> Caddy public origin
       -> /chat and static assets
       -> Agent API: CopilotKit React Core over AG-UI
            -> private Agent Host
                 -> CopilotKit Runtime and AgentRunner
                 -> Mastra Research Agent and current-thread Memory
                 -> startup model registry and provider credentials
                 -> Agent-owned PostgreSQL schema
                 -> Auth session verification and token exchange
                 -> Core /mcp with a short-lived Researcher token
                      -> Core modules and Product State
                      -> Research, Batch Research, and Tracking Workers
                      -> RustFS Result Bundles and mounted Canonical Data
       -> ordinary Core API for non-Agent product pages
```

For each Agent Run, the Agent Host authenticates the Better Auth Login Session,
loads the requested model and supported reasoning effort from its startup registry,
exchanges the Login Session for a short-lived OAuth token, discovers the visible
Tools from `/mcp`, and gives every discovered Tool to Mastra. The OAuth grant carries
read and execute scopes for Research and Tracking. It omits Research cancellation
and DailyTrack Stop scopes, so the destructive Tools are not discoverable. There is
no separate Host allowlist, confirmation interrupt, or browser approval flow.

Mastra decides which Tool arguments to provide, which Research Folder is appropriate,
whether an idea needs clarification, whether to diagnose or revise a Formula, and
whether to poll a submitted resource or respond immediately. It also owns the
current-thread message history and Agent Run loop. CopilotKit AgentRunner owns
thread/run identity and same-thread concurrency. ThesisTrace supplies startup
bounds and product integration but adds no Folder-selection state machine,
ResearchRun watcher, prompt lifecycle, or durable Agent job queue.

Assistant output may combine ordinary safe Markdown, compact Tool activity, and
A2UI payloads. A2UI is used directly through a registered catalog of standard
primitives and ThesisTrace components; it is not limited to one hard-coded Alpha
card. The browser still renders only registered components and declared properties,
never model-authored HTML, JavaScript, CSS, or network requests. Browser-side A2UI
actions are limited to navigation, expand/collapse, and copy. Any Research mutation
is initiated by the Agent through MCP.

Chat persistence and Research persistence remain independent. The Agent Host stores
Threads, Messages, Run metadata, Tool events needed for replay, A2UI state, titles,
and current model preference in its own PostgreSQL schema and role. Core stores
ResearchRun, Research Batch, DailyTrack, and Result truth. Neither schema has a
cross-database ownership shortcut or cascade. Chat may retain opaque Core identifiers
as message content, but deletion never queries Core to find or alter those resources.

## User Stories

1. As a Researcher, I want to describe an investment idea in ordinary language so that I can generate and test an Alpha without manually writing the whole Formula first.
2. As a Researcher, I want Chat to be a standalone page so that conversational research does not crowd or change the manual Research workspace.
3. As a Researcher, I want Chat to appear as a primary product destination so that it is reachable from every authenticated workspace page.
4. As a Researcher in Chat, I want Data, Research, Research Runs, and Daily Tracks near the top of the sidebar so that workspace navigation is visible before conversation history.
5. As a Researcher, I want a prominent New Chat action so that starting a separate line of reasoning is immediate.
6. As a Researcher, I want an untouched New Chat to remain ephemeral so that opening and abandoning it does not create empty database records.
7. As a Researcher, I want the first submitted message to create the durable Chat Session so that persistence begins only when the conversation has content.
8. As a Researcher, I want the first conversation to receive a concise model-generated title so that the session list remains scannable.
9. As a Researcher, I want to rename a Chat Session so that I can replace an unhelpful generated title.
10. As a Researcher, I want to delete a Chat Session from its sidebar menu so that I can remove its Messages and generated UI.
11. As a Researcher, I want Chat deletion to leave every ResearchRun, Research Batch, DailyTrack, and Result unchanged so that Research has an independent lifecycle.
12. As a Researcher, I want recent sessions ordered and grouped by time so that I can resume current work quickly.
13. As a Researcher, I want session history to load in bounded pages so that a long-lived account does not make Chat startup unbounded.
14. As a Researcher, I want the selected session represented in the URL so that refresh, browser history, and a copied same-origin link reopen the same conversation.
15. As a Researcher, I want a missing or deleted session URL to show an explicit not-found state and a New Chat action so that it never silently opens another person's or another session's content.
16. As a Researcher, I want a reloaded Chat Session to replay its Messages, Tool activity, and A2UI state so that the visible conversation remains coherent.
17. As a Researcher using two devices, I want both clients opening the same Session to identify the same active Agent Run so that they do not start competing turns accidentally.
18. As a Researcher, I want different Chat Sessions to run independently so that one experiment does not block unrelated conversations except at deployment capacity limits.
19. As a Researcher, I want the Agent to remember only the current Chat Session so that an unrelated transcript cannot silently influence the current Alpha.
20. As a Researcher, I want the Agent to inspect my authorized Research through MCP so that it can compare or explain prior Research without cross-session conversational memory.
21. As a Researcher, I want another Researcher's Chat identifier to return not found so that conversation ownership cannot be enumerated.
22. As a Researcher, I want V1 input to be text-only so that the first release has one clear and reliable authoring path.
23. As a Researcher, I want assistant text to stream while the Agent works so that a long turn does not look frozen.
24. As a Researcher, I want compact Tool activity to show discovered Tool name, running or terminal state, and safe timing so that I can understand what the Agent is doing.
25. As a Researcher, I want Tool activity to hide raw credentials and internal payloads so that observability does not become a secret or research-content leak.
26. As a Researcher, I want the Agent to render an Alpha Proposal with hypothesis, Formula, universe, period, and interpretation when those values are useful so that the result is easier to inspect than prose alone.
27. As a Researcher, I want completed Research results rendered with suitable A2UI tables, metrics, status, and navigation so that quantitative output is readable inside the conversation.
28. As a Researcher, I want A2UI navigation actions to open the authoritative Research page so that Chat does not pretend to replace the Research object.
29. As a Researcher, I want copy and expand actions in generated UI so that I can reuse a Formula and inspect dense details without triggering a business mutation.
30. As a Researcher, I want the Agent to call MCP without a confirmation dialog so that ordinary read and execute work remains conversational and autonomous.
31. As a Researcher, I want the Agent to receive every Tool returned by its authenticated MCP discovery so that ThesisTrace does not maintain an inconsistent second Tool list.
32. As a Researcher, I want cancellation and Stop Tools absent from this Agent's discovery while no approval flow exists so that dangerous actions cannot be invoked accidentally.
33. As a Researcher, I want the Agent to choose a Research Folder from MCP context and Tool schemas so that Chat does not require a separate Folder selector.
34. As a Researcher, I want the Agent to use reliable platform defaults for a sufficiently clear idea so that it does not ask unnecessary setup questions.
35. As a Researcher, I want the Agent to ask a follow-up only when missing intent would materially change the research so that vague requests are corrected instead of guessed recklessly.
36. As a Researcher, I want the Agent to decide whether to diagnose a Formula before submitting it so that orchestration remains model-owned rather than a fixed backend wizard.
37. As a Researcher, I want the Agent to decide whether and how long to poll a ResearchRun so that Core and the Agent Host do not duplicate a polling workflow.
38. As a Researcher, I want work already admitted by MCP to continue when the Chat stream disconnects or the Agent Run ends so that Core work is not owned by a conversation connection.
39. As a Researcher, I want a later message to inspect a durable Research identifier returned earlier so that I can resume explanation after a bounded Agent Run ends.
40. As a Researcher, I want one Chat Session to produce multiple ResearchRuns when the idea requires comparison so that the conversation is not artificially one-to-one with Research.
41. As a Researcher, I want a model selector populated from system configuration so that I can choose among only the providers the Operator has registered.
42. As a Researcher, I want the model selector to show a stable display name without exposing provider credentials or secret environment names.
43. As a Researcher, I want a reasoning-effort selector constrained by the chosen model so that I cannot request an unsupported setting.
44. As a Researcher, I want a model or reasoning change to apply to the next submitted message so that I can change approach within the same Session without rewriting history.
45. As a Researcher, I want each completed Agent Run to retain the actual model and reasoning effort used so that historical output is not relabeled after my selection changes.
46. As a Researcher, I want an unavailable or failed model to fail the current Agent Run visibly so that ThesisTrace never switches providers without telling me.
47. As a Researcher, I want to retry explicitly or select another registered model after failure so that recovery stays under my control.
48. As an Operator, I want model registrations and supported reasoning efforts read once at Agent Host startup so that the available catalog is deployment-controlled and deterministic.
49. As an Operator, I want duplicate model keys, an unknown provider adapter, unsupported reasoning configuration, or a missing credential to fail startup so that a broken catalog never becomes a partial UI.
50. As an Operator, I want provider credentials available only to the Agent Host so that the browser, Auth, Core, Workers, and persisted Chat records never receive them.
51. As an Operator, I want the Mastra Agent's deployed `instructions` to be the system prompt so that there is no second prompt registry, editor, or lifecycle to synchronize.
52. As a logged-in Researcher, I want my existing Better Auth Login Session to authenticate Chat so that there is no second login or API-key flow.
53. As a Researcher, I want the browser to send only its same-origin Login Session to the Agent API so that it never sees or stores the MCP OAuth token.
54. As a Core operator, I want Auth to exchange an active Login Session for one short-lived token with the Researcher as subject and canonical `/mcp` as audience so that Core can enforce current ownership and scopes.
55. As a Core operator, I want the token lifetime to exceed the bounded Agent Run lifetime by a fixed safety margin so that no refresh token or durable Login Session copy is required inside the Agent Host.
56. As a Core operator, I want every new Agent Run to use a fresh authentication and Tool-discovery cycle so that revoked Sessions and changed grants fail closed on the next turn.
57. As a Researcher whose Session expires or is deactivated, I want a clear authentication failure and no continued Agent Tool access so that Chat cannot outlive account authority.
58. As a Core owner, I want all Agent-created Research to pass through `/mcp` and existing module invariants so that Chat cannot bypass idempotency, ownership, Data Generation pinning, or Worker admission.
59. As a Core owner, I want the Agent Host to have no Core database, Auth database, RustFS, queue, or Canonical Data credentials so that a compromised model runtime cannot become a second Research authority.
60. As a Researcher, I want only one active Agent Run per Chat Session so that two overlapping messages cannot corrupt the conversational order.
61. As a Researcher, I want the composer disabled while the current Agent Run is active so that the user interface matches AgentRunner's same-thread concurrency contract.
62. As a Researcher, I want reconnecting to an active or completed Run to restore its persisted state so that a network interruption does not create a duplicate turn.
63. As a Researcher, I want Agent Run limits to produce a visible bounded failure while preserving completed Tool outcomes so that I can continue intentionally in a later message.
64. As a Researcher, I want model, Auth, MCP, validation, and provider failures distinguished in the conversation so that I know whether to retry, revise the request, log in, or choose another model.
65. As a Researcher, I want the composer and latest state visible at the bottom of long conversations so that sending the next message does not require navigating away from context.
66. As a keyboard user, I want session navigation, menus, model selection, the composer, generated controls, and focus restoration fully operable so that Chat does not require a pointer.
67. As a narrow-screen user, I want the session sidebar to become an off-canvas drawer while conversation content retains its meaning so that Chat remains usable without a permanent rail.
68. As a Researcher, I want Chat to use ThesisTrace's near-black surfaces, compact type, hairlines, and restrained lavender focus language so that it feels like the same product rather than a pasted chatbot widget.
69. As a Researcher, I want user messages, assistant prose, Tool activity, Formulae, and Research results to have distinct but restrained hierarchy so that dense conversations remain scannable.
70. As a Researcher, I want explicit empty, loading, streaming, complete, failed, and disconnected states with text so that status never depends on color or animation.
71. As a security reviewer, I want model prompts, Messages, A2UI, Formulae, hypotheses, Tool arguments and results, Cookies, credentials, and tokens excluded from logs and traces so that operational telemetry is not a second content store.
72. As an Operator, I want sanitized telemetry for Researcher correlation, Session and Run identifiers, model, reasoning effort, token usage, step count, duration, status, and error category so that reliability and cost remain measurable.
73. As a test author, I want a Scripted Fake Model to drive deterministic Tool calls and A2UI events so that engineering tests assert product behavior instead of model prose.
74. As a test author, I want real Auth, PostgreSQL, Agent Host, Core MCP, Workers, RustFS, and Fixture data behind that Fake Model so that mocks do not hide ownership, persistence, queue, or Research lifecycle defects.
75. As an acceptance tester, I want the complete loop exercised through Caddy and a real browser so that component-level success cannot hide broken same-origin routing, streaming, focus, or session behavior.
76. As a model evaluator, I want real-model quality measured separately on a fixed idea corpus so that probabilistic success, cost, latency, Tool errors, and variance do not make deterministic CI flaky.
77. As a release operator, I want final Production Image Smoke to prove the private Agent Host, exact routes, startup configuration, Auth exchange, MCP discovery, one Agent-created ResearchRun, restart behavior, and content redaction so that source-only success cannot qualify a release.

## Implementation Decisions

### Product and visual structure

- Add Chat as a primary authenticated destination. Do not embed it in Research, add a Research-page Chat panel, or turn Alpha Proposal into a Research Draft mode.
- On ordinary resource pages, include Chat in the application navigation alongside Data, Research, Research Runs, and Daily Tracks. On `/chat`, use a session-oriented sidebar whose upper area contains the ThesisTrace identity, New Chat, and those four workspace links; place Chat history beneath them and the account control at the bottom.
- Keep the workspace links above session groups. Do not reproduce ChatGPT sections such as Projects, GPTs, plugins, scheduled tasks, or pinned conversations unless ThesisTrace later gains those products.
- Apply the repository design system as a hard cut: near-black canvas, stepped charcoal surfaces, hairline borders, compact typography, restrained lavender focus and primary actions, semantic colors only for state, no gradients, glow, glass, ornamental card stacks, or parallel light theme.
- Use a centered reading column for ordinary conversation, with a wider bounded region available to dense A2UI results. Keep the composer anchored at the bottom of the conversation region without covering the latest content.
- Distinguish the Researcher's messages, assistant prose, Tool activity, and generated Research UI through alignment, typography, surface steps, and labels rather than bright role colors or oversized avatars.
- The 48-pixel Chat header shows the session title and current model context. Model and reasoning controls may live in the header or composer controls, but there is one authoritative selection and no duplicate settings panel.
- Group session history by recency and order it by most recent activity with a stable identifier tie-break. Load 30 at a time. A collapsed desktop sidebar preserves New Chat, workspace destinations, and accessible session access; mobile uses an off-canvas drawer.
- New Chat has no durable identifier. After the first message is accepted, replace the ephemeral URL with the opaque persisted Session identity without a document reload.
- Provide rename and delete in an accessible session menu. Session deletion requires an explicit short decision because it is irreversible Chat deletion, but it is not an Agent Tool approval and never describes or affects Research resources.

### Frontend runtime, streaming, and A2UI

- Use CopilotKit React Core v2 headlessly. Compose the ThesisTrace Chat page from project components rather than adopting a prebuilt CopilotKit visual shell or AI SDK UI abstraction.
- Use AG-UI as the sole browser-to-Agent event protocol for message, lifecycle, Tool, state, and generative-UI streaming. Do not add a parallel custom SSE transcript protocol or reconstruct Agent state from plain token text.
- Use A2UI directly through a version-pinned renderer and a registered component catalog containing suitable standard primitives plus ThesisTrace-specific Formula, Alpha Proposal, ResearchRun, Batch, DailyTrack, metric, table, provenance, and status components.
- Validate every A2UI envelope, component identifier, property, child relationship, and action before rendering or persisting it. Unknown or invalid payloads produce an explicit safe rendering error; they never execute arbitrary markup or script.
- A2UI components receive declarative data only. They cannot access provider credentials, the MCP token, raw Cookies, arbitrary URLs, or a general fetch callback.
- Browser A2UI actions are limited to same-origin navigation to an authorized product route, local expand or collapse, and copy. Research submission, retry, Batch admission, and DailyTrack start remain Agent-to-MCP Tool calls.
- Persist validated A2UI state with the owning Message or Thread so replay after reload renders the same interface without asking the model to regenerate it.
- Render ordinary assistant content as sanitized Markdown with Formulae and identifiers using the product mono style. Never allow raw HTML from the model.
- Tool activity exposes only Tool name, lifecycle state, safe resource identifier when already public to the Researcher, elapsed time, and sanitized outcome summary. Raw arguments and full Tool results remain model history, not automatically expanded browser diagnostics.
- The browser must handle reconnect and replay using CopilotKit/AG-UI run identity. It must not submit the last user message again merely because a stream was interrupted.

### Agent Host and framework ownership

- Add one private TypeScript Agent Host that combines CopilotKit Runtime, CopilotKit AgentRunner, `@ag-ui/mastra`, one Mastra Agent, Mastra Memory, model-provider adapters, and the Mastra-supported MCP client. Do not split these into independent product services in V1.
- Define the built-in Research Agent as: deployed Mastra `instructions` + the Researcher-selected registered model and reasoning effort + current Thread Memory + every Tool returned by the current authenticated `/mcp` discovery.
- Mastra owns instructions, model invocation, Tool choice, Tool argument construction, Memory selection, context-window management, step progression, polling decisions, and final response generation. Do not add a ThesisTrace Agent planner, Folder chooser, Formula workflow, ResearchRun watcher, or prompt database.
- CopilotKit AgentRunner owns Thread/Run identity and same-thread concurrency. Use its supported rejection or attachment behavior for overlapping runs; do not introduce an `Agent Session Busy` domain state, queue table, lease protocol, or custom resumable-job state machine.
- One Thread has at most one active Agent Run. The UI disables submission while it observes that run. A second client binds to the same Thread and Run state; different Threads may run independently within fixed deployment capacity.
- Once Core has accepted a ResearchRun, Research Batch, or DailyTrack action, Agent cancellation, stream loss, Host restart, or Agent Run timeout does not cancel or mutate it. A future Agent Run can rediscover it through MCP if the conversation retained its identifier or the Agent locates it through authorized list Tools.
- V1 does not enable CopilotKit interrupts, pause/resume, human approval, or browser-side Agent cancellation. While a framework Run is active, session deletion is not offered; deletion never serves as an implicit interrupt.
- Configure fixed maximum message bytes, context tokens, model output tokens, Tool steps, Tool result bytes, and Agent Run wall time at startup. Select and pin the concrete values from deterministic load tests and real-model Eval before release; they are not Researcher-controlled settings.
- Use framework-supported persistence and replay rather than retaining active Run state only in process memory. Host restart may fail the interrupted model invocation, but the Thread, completed Messages, completed Tool outcomes, and any Core resources remain durable and visible.

### MCP capability use

- Connect the Agent only to Core's canonical OAuth-protected `/mcp` endpoint. The Agent Host must not call Core product HTTP routes, repositories, queues, RustFS, or mounted Canonical Data as an alternate Tool path.
- At the start of each Agent Run, authenticate the current Login Session, exchange it for a short-lived MCP token, establish the MCP client, and discover the visible Tool set. Supply that discovered set directly to Mastra for the run.
- Do not encode the eighteen Core Tool names or a product-selected subset in the Agent Host. The current inventory is whatever `/mcp` returns after intersecting the Core deployment policy with the OAuth grant.
- Grant the built-in Agent `research:read`, `research:execute`, `tracking:read`, and `tracking:execute`. Omit `research:cancel` and `tracking:stop`; their Tool definitions remain in Core but are absent from this Agent's discovery.
- Do not reinterpret MCP annotations as authorization and do not add a confirmation token. Core repeats scope, ownership, lifecycle, input, and idempotency checks on invocation.
- Let the Agent choose Folder, Formula, Research type, dates, universe, neutralization, Strategy parameters, Batch shape, polling, and result sections from conversation plus Tool descriptions and context. The Host validates only protocol and configured execution bounds.
- Preserve MCP structured outcomes as model-visible Tool results. Correctable Formula diagnostics and admission rejection remain ordinary structured results; authentication, authorization, lifecycle, transport, and internal failures retain their stable MCP error meaning.
- Do not automatically retry a model with another model. MCP transient retry follows Tool-provided retry guidance and Mastra's bounded run behavior; the Agent decides whether a retry is appropriate within the current run.

### Model registration and selection

- Read one model registry from system configuration during Agent Host startup. Each enabled entry has a stable key, display name, provider adapter, provider model identifier, supported reasoning efforts, default reasoning effort, and a reference to the required secret environment variable.
- Validate the whole registry before the Host becomes ready. Reject duplicate stable keys, duplicate ambiguous display identities, disabled defaults, unknown adapters, empty model identifiers, unsupported reasoning labels, inconsistent defaults, and missing credentials.
- Provider API credentials exist only in the Agent Host process environment. Never return them or their environment-variable names to the browser, persist them in Chat state, pass them through Auth, or expose them to MCP.
- Publish a safe model catalog from the authenticated Agent API. The browser sends a registered model key and one advertised reasoning effort with each new message.
- Store the current selection as Thread preference for convenience, but record the actual stable model key, provider model identifier, reasoning effort, Agent build revision, token usage, and terminal status on each Agent Run. Changing the preference affects only later Runs.
- If an existing Thread references a model no longer enabled after deployment, preserve historical labels and require a current selection before the next Run. Do not silently substitute the deployment default.
- The Agent's system prompt is Mastra `instructions` shipped with the Agent Host artifact. Do not add a prompt table, prompt editor, prompt version UI, startup prompt file registry, or per-Researcher system prompt.
- V1 exposes model and reasoning effort only. Temperature, top-p, provider-specific knobs, token budgets, endpoint overrides, and bring-your-own-key are not Researcher settings.

### Authentication and authorization

- Reuse the existing Better Auth Login Session. The Agent Host verifies the original Cookie through the existing private Auth adapter on every Agent Run and fails closed for invalid, expired, revoked, inactive, malformed, unavailable, or cross-origin requests.
- Add an Auth-owned private exchange that issues a short-lived OAuth access token for the verified Researcher. Its subject is the Researcher ID, its audience is the canonical `/mcp` resource, its client identity is the built-in Agent, and its scopes are the four approved read and execute scopes.
- Set the token lifetime longer than the maximum Agent Run wall time plus a fixed clock-skew margin. Validate this relationship at startup. Do not issue a refresh token, persist the access token, or persist the Login Session Cookie in the Agent database.
- Hold the Cookie and access token only in memory for the current request or Agent Run and redact them from exceptions, model context, messages, A2UI, logs, traces, and diagnostics.
- The browser never calls `/mcp` for Agent execution and never receives the OAuth token. It calls only the same-origin Agent API with the normal Cookie and anti-CSRF origin protections.
- Map Mastra resource identity to the authenticated Researcher ID and enforce that identity on every Thread, Message, Run, title, list, rename, and delete operation. Cross-Researcher identifiers return not found.
- Agent Host authorization is limited to its own schema and Auth/MCP network calls. Its runtime database role has no privileges on Auth or Core schemas; it receives no RustFS, queue, Worker, Canonical Data, or Core database credentials.

### Chat persistence and Research independence

- Give the Agent Host a dedicated PostgreSQL schema, initializer, owner, and runtime role. Pin the Mastra/CopilotKit storage dependency versions and keep runtime startup schema-verifying rather than migration-performing.
- Use Mastra's supported PostgreSQL Memory and Thread model as the durable conversation authority. Store only the smallest ThesisTrace metadata needed for Researcher ownership, title, current model preference, A2UI replay, and safe Run history; do not duplicate framework Run state into a product state machine.
- A Chat Session is owned directly by one Researcher. There is no Chat Workspace, sharing, organization, membership, collaboration, public link, or Core Research Folder parent.
- Current-thread Memory is the only conversational Memory supplied to the Agent. Disable cross-thread semantic recall, account-wide transcript search for model context, global working memory, and another Researcher's Memory.
- An Alpha Proposal is validated A2UI or message state inside Chat. It is not a Core entity, immutable Research snapshot, Research Draft, Factor, Result, or promise that a ResearchRun exists.
- A Chat Session may contain zero, one, or many opaque Core identifiers returned by MCP. Do not create a foreign key, join table, cascade, ownership shortcut, or deletion query between Agent and Core schemas.
- Deleting a Chat Session deletes its Thread, Messages, associated A2UI state, title, and Agent Run records using the Agent store. It does not enumerate, cancel, stop, delete, relabel, or otherwise mutate Core resources.
- Renaming or deleting Research in Core does not rewrite Chat history. Chat renders historical identifiers and handles later MCP not-found outcomes explicitly.
- Generate the initial title after the first accepted user message through a bounded framework model operation and persist it as Thread metadata. Title failure does not fail or roll back the primary Agent Run; the Session remains visibly untitled until a later generated or manual rename succeeds.

### Routing, deployment, and health

- Keep Caddy as the only public listener and same-origin authority. Route Agent API traffic to the private Agent Host before the generic Core API matcher, route exact `/mcp` and its required protected-resource metadata to Core, and retain the SPA fallback for `/chat` navigation.
- Add the Agent Host and a separate Agent schema initializer to the existing Compose and Production image topology. Publish no Agent Host port on the host network.
- Give the Agent Host provider secrets and Agent database credentials only. Give Auth the OAuth signing authority and Core the corresponding verifier configuration. Do not share the Auth signing secret with the Agent Host.
- Enable Core's production `/mcp` construction with the real verifier and deployment allowlist. Missing issuer, audience, verifier, allowed origin or host, or Agent scope configuration fails startup rather than disabling authentication or silently removing the route.
- Agent Host liveness is process-local. Readiness validates its exact Agent schema, model registry, required secret presence, and bounded connectivity to Auth and Core MCP metadata without making a paid model request.
- Caddy and the static Chat page remain able to show an explicit dependency-unavailable state when the Agent Host, Auth, Core, or provider is unavailable. Do not replace it with an empty conversation or automatic alternate backend.
- Pin CopilotKit, AG-UI, A2UI, Mastra, model-provider, and storage packages to reviewed versions. Upgrade them only through an explicit hard cut and regenerated schema/protocol evidence; add no compatibility adapter or fallback implementation.

### Failure behavior and observability

- Distinguish authentication required, Agent unavailable, invalid model selection, unsupported reasoning effort, provider unavailable, provider refusal, Agent limit reached, MCP authentication failure, MCP transient failure, Tool rejection, Tool error, invalid A2UI, and unexpected internal failure in stable safe UI states.
- A failed Agent Run never triggers another model automatically. Keep already completed Messages, Tool outcomes, A2UI, and returned Core identifiers; allow the Researcher to retry with the same or another registered selection in a new Run.
- An Agent wall-time or step-limit failure stops only model orchestration. It does not cancel admitted Core work, start a server-side watcher, or create a hidden continuation job.
- Emit Agent Host telemetry from a closed metadata allowlist: pseudonymous Researcher correlation, Thread ID, Run ID, trace ID, model key, provider model identifier, reasoning effort, token usage, step count, duration, status, retry classification, and sanitized error category.
- Exclude user and assistant Messages, model request and response bodies, Mastra Memory, system instructions, A2UI payloads, Alpha Formulae, Investment Hypotheses, MCP arguments and results, Cookies, OAuth tokens, provider credentials, storage records, and stack traces containing private values from logs and traces.
- Product content is durable only in owner-scoped Agent Chat storage or existing Core Product State. Telemetry cannot be replayed as Chat history and is never a recovery authority.

## Testing Decisions

- The confirmed primary test seam is one complete authenticated `/chat` user loop through Caddy in an isolated Compose environment. It uses the real Web application, Better Auth, Agent Host, Agent PostgreSQL schema, Auth and Core schemas, Core `/mcp`, Workers, RustFS, and Fixture-backed Canonical Data. Only the remote model is replaced by a deterministic Scripted Fake Model.
- Drive that seam with a real browser. Cover login, empty New Chat, model and reasoning selection, first-message Thread creation, AG-UI streaming, MCP discovery, context and Alpha catalog reads, Formula diagnosis, ResearchRun admission, bounded polling, Result inspection, A2UI rendering, session title, reload replay, navigation to Research, and accessible terminal status.
- In the primary loop, assert behavior and durable artifacts rather than exact assistant prose. The Scripted Fake Model controls Tool choices and A2UI events; the test asserts that the intended ResearchRun and Result exist and that the visible conversation reports their safe identifiers and status.
- Extend the primary seam with a deletion proof: record the created Core ResearchRun and Result, delete the Chat Session, prove all Agent Thread, Message, Run, and A2UI records are gone, and then prove the same Core ResearchRun and Result remain readable and unchanged.
- Extend the primary seam with two Researchers. Prove that each sees only their model-safe Session list and Chat state, cross-Researcher Session identifiers return not found, and Core MCP ownership remains the existing Researcher scope.
- Add a same-thread concurrency acceptance case with two browser contexts. One starts a scripted long Agent Run; both bind to the same Run state, the second cannot submit an overlapping turn, completion appears after reconnect or replay, and exactly one ordered user turn is persisted.
- Add a disconnect and Host-restart case. Interrupt the AG-UI connection after at least one completed Tool call, restart the Agent Host, reopen the Session, and prove persisted Messages and completed Tool outcomes replay without resubmitting the user message. Any already-admitted Core work must continue independently.
- Keep Agent Host contract tests thin and public-boundary focused. Through its authenticated HTTP/AG-UI surface, cover event ordering, Run identity, replay, same-thread concurrency, malformed messages, size and step limits, terminal errors, title generation, rename, deletion, and cross-Researcher ownership. Do not unit-test private framework callbacks or assert internal call counts.
- Use real isolated PostgreSQL for Mastra Memory, Thread, Run, ownership, concurrency, restart, and deletion tests. Do not replace the Agent store, Auth store, Core store, queue, Workers, or RustFS with mocks.
- Add model-registry startup tests for a valid multi-provider catalog and every fail-closed condition: missing default, duplicate key, ambiguous identity, disabled selection, unknown adapter, unsupported or empty reasoning set, invalid default reasoning, missing provider secret, and invalid Agent-run/token-lifetime relationship.
- Add selection contract tests proving the safe catalog, per-model reasoning choices, next-Run changes, historical actual-model metadata, removed-model behavior, unsupported selection rejection, and absence of secret values or environment-variable names from browser responses.
- Add deterministic provider-failure cases for timeout, rate limit, authentication failure, malformed stream, refusal, output limit, and unexpected error. Assert no automatic model fallback, no duplicate user message, safe error copy, durable completed Tool outcomes, and explicit Researcher-controlled retry.
- Add Auth exchange integration tests using real Auth and Core verifier boundaries. Cover valid active Session, invalid Cookie, expiry, revocation, deactivation, wrong origin, Auth timeout, malformed exchange, wrong issuer, wrong audience, wrong subject, wrong client identity, expired token, missing scope, and startup failure when production verification is incomplete.
- Add exact discovery tests proving the Agent Host passes through the MCP-discovered inventory without a duplicated name list. With the approved grant, read and execute Tools are visible and every cancel or Stop Tool is absent. A stale or forged invocation remains denied by Core.
- Reuse and extend the existing Core MCP protocol, scope, ownership, idempotency, pagination, structured-error, redaction, and deterministic trajectory suites. Do not recreate Core lifecycle tests inside the Agent Host simply to increase coverage.
- Add Scripted Fake Model trajectories at the real Agent boundary for a direct valid Alpha idea, invalid Formula correction, materially ambiguous idea with one follow-up, Strategy Backtest, Research Batch, DailyTrack start and inspection, transient MCP backoff, bounded polling exit, and a Tool rejection the Agent explains without hiding it.
- Add A2UI contract tests for every registered standard and ThesisTrace component, nested composition, Formula and metric formatting, large bounded tables, persisted replay, keyboard behavior, unknown components, invalid props, disallowed actions, unsafe URL attempts, raw HTML, script, CSS, and arbitrary network actions.
- Add browser behavior tests for session grouping and pagination, New Chat ephemerality, URL selection and history, automatic and manual title, rename, delete decision, missing Session, account switch, scroll anchoring, composer disablement, focus restoration, and explicit loading, disconnected, error, and empty states.
- Add responsive and accessibility acceptance at expanded desktop, collapsed desktop, tablet, and mobile widths. Verify no horizontal page overflow, off-canvas session navigation, minimum touch targets, semantic roles, labels, contrast, keyboard-only operation, visible focus, reduced motion, and status text independent of color.
- Add redaction canaries in a user message, system instruction, Formula, hypothesis, A2UI payload, MCP arguments and results, Cookie, OAuth token, provider key, and provider response. Scan Agent, Auth, Core, Caddy, Worker, and test diagnostics to prove private values never enter logs, traces, health responses, or image-smoke evidence.
- Add architecture tests proving the Agent Host package and runtime configuration have no Core repository, Core database, Auth database, RustFS, queue, Worker, or Canonical Data dependency; the browser has no provider or MCP credential; and only Auth owns token signing.
- Add Caddy and Compose contract tests for route order, `/chat` SPA fallback, exact Agent API routing, exact `/mcp` routing, protected-resource metadata, same-origin and CSRF behavior, private Agent Host networking, separate database roles, and only Caddy host port bindings.
- Extend Production Image Smoke to use final built images and isolated real dependencies. Verify schema initialization and verification, startup failure on invalid model/Auth/MCP configuration, safe readiness, model catalog, one complete Fake-Model Chat-to-Research loop, Agent Host restart and replay, Chat deletion independence, and log redaction.
- Keep deterministic tests offline and free of paid provider calls. Fix clock, timezone, UUIDs, randomness, model events, Tool responses where externally scripted, and Fixture data. Use bounded condition polling with diagnostic output; never use arbitrary sleep or test-order-dependent shared state.
- Run real-model Eval separately from deterministic CI against a fixed, versioned corpus covering clear idea-to-Alpha, ambiguous intent, Formula repair, Strategy comparison, Batch use, long Research polling, and result explanation. For every registered model and reasoning effort under consideration, measure task success, invalid-Tool rate, Tool retry rate, cost, token use, P50/P95 latency, and multi-run variance before enabling it.
- Pin release thresholds, maximum Agent steps, context and output limits, wall time, and provider-specific reasoning mapping from the measured Eval and production resource envelope. A model that misses the pinned gate remains disabled; deterministic engineering tests do not become probabilistic retries.
- Finish with in-app-browser acceptance on the final local production-like stack. Visually inspect the Chat hierarchy, workspace-link placement, session sidebar, streaming and Tool states, A2UI density, model controls, deletion wording, Research navigation, desktop collapse, and mobile drawer against the repository design system.
- Integrate the deterministic unit, integration, browser, architecture, and Production Image Smoke suites into the repository's reproducible check and release gates. On failure, retain sanitized AG-UI event order, trace and Run identifiers, model key, reasoning effort, dependency state, exit codes, random seed, screenshots, and image versions.

## Out of Scope

- Embedding Agent Chat in the Research workspace or replacing the manual Research editor.
- A browser-side Agent, direct browser-to-model request, direct browser-to-MCP execution, or provider credentials in frontend code.
- A second ThesisTrace Tool registry, Host-authored wrappers around individual MCP Tools, request-selected Tool subsets, or compatibility aliases.
- Research cancellation, Research Batch cancellation, DailyTrack Stop, CopilotKit interrupts, pause/resume, human approval, or confirmation-token flows in V1.
- Browser A2UI actions that submit, retry, cancel, stop, delete, or otherwise mutate Core Product State.
- Arbitrary model-authored HTML, CSS, JavaScript, custom React source, iframe content, external image URLs, or general browser network actions.
- Cross-session Agent Memory, semantic recall across Chat Sessions, account-wide transcript retrieval for model context, shared Memory, or another Researcher's content.
- Chat sharing, public links, collaboration, projects, nested Chat folders, pinning, archiving, bulk deletion, transcript export, or global Chat search.
- File, image, audio, dataset, spreadsheet, PDF, or code upload; voice input or output; browser or shell Tools.
- Researcher-managed provider credentials, bring-your-own-key, runtime provider registration, model hot reload, model marketplace, temperature controls, or automatic model routing and fallback.
- A custom prompt manager, prompt editor, prompt database, prompt version UI, per-Researcher system prompt, or a ThesisTrace-owned Agent planning language.
- A custom Agent job queue, ResearchRun watcher, polling daemon, Folder selection workflow, Agent Session lease, or durable continuation scheduler outside Mastra and CopilotKit.
- A Core foreign key or cascade from Chat, a one-to-one Chat-to-Research relationship, Alpha Proposal as a Core resource, or rewriting Chat when Research changes.
- Agent Host access to Core or Auth database tables, RustFS objects, mounted Canonical Data, Worker queues, or private Research implementation APIs.
- Modifying the economic meaning, Formula semantics, admission rules, ownership rules, Data Generation pinning, execution lifecycle, or Result contract of ResearchRun, Research Batch, or DailyTrack.
- SaaS quotas, billing, credits, per-model pricing UI, organization roles, shared Research ownership, or administrator Chat inspection.
- Multi-region execution, Agent Host high availability, zero-downtime schema upgrades, external load balancers, DNS, WAF policy, or public rollout operations.
- Backward compatibility, fallback styling, legacy Agent endpoints, parallel AI SDK UI code, dual storage, runtime schema migration, or migration of prototype in-memory sessions.

## Further Notes

- This specification implements ADR-0235 through ADR-0238: the separate Agent Host, independent Chat and Research lifecycles, Login Session to short-lived MCP token exchange, and content-free operational telemetry are required boundaries rather than optional implementation suggestions.
- Existing Research Agent MCP decisions remain authoritative. The built-in Agent consumes that contract as an authenticated Host; it does not redefine Core Tools, scopes, structured errors, idempotency, pagination, or durable Research behavior.
- The visual prototype is evidence for information architecture and interaction direction only. Production implementation must use the real authenticated shell, the current repository design system, durable Agent storage, CopilotKit/AG-UI/A2UI, Mastra, and Core MCP rather than copying prototype state or CSS mechanically.
- The testing seam confirmed before publication is the complete Caddy-to-Chat-to-Agent-to-MCP-to-Worker-to-Result loop with all owned infrastructure real and only the model scripted. Thin protocol and image gates support that seam; real-model Eval remains separate.
- Recheck and pin the current supported CopilotKit, AG-UI, A2UI, Mastra, storage, and provider versions during implementation. Use only documented stable integration points; if a required capability is absent, stop and revise the architectural decision instead of adding a temporary compatibility implementation.
- This is a feature specification published to the local issue tracker with the canonical `ready-for-agent` status. It does not create implementation tickets, authorize a production deployment, or claim that the existing visual prototype is production-integrated.
