# Agent Chat telemetry

Agent stderr contains JSON metadata, not a transcript. `agent_run_accepted`
means durable admission, `agent_tool_finished` observes an MCP/A2UI outcome, and
`agent_run_finished` is emitted once for an observed terminal Run. Duplicate
requests and history replay do not count as new execution. HTTP/readiness and
startup/shutdown retain their separate, content-free operational envelopes.

All Run events use the same closed fields: pseudonymous Researcher correlation,
Thread/Run/Trace UUIDs, selected Model Key/Provider Model ID/Reasoning Effort,
Token Usage, Step Count, Duration, Status, Retry Classification and Error
Category, plus fixed event/component/level and UTC timestamp fields. The
Researcher correlation is a domain-separated SHA-256 of the internal UUID,
never an email, display name or raw Researcher ID. Trace IDs must be UUIDs.
Provider model identifiers cannot be URLs, paths or free-form text.

`duration_ms` is monotonic elapsed Run time, including on Tool events;
`step_count` counts provider invocations. `token_usage` is cumulative over those
invocations. Sum only terminal Run observations, not every Tool observation.
Unknown counters are `null`; a missing/invalid/pending provider usage report
makes the Run's accounting `{ "reported": false }`, never fabricated zero.
Independent title generation is not included in primary Run usage. Retry
classification names the available explicit user recovery, not an automatic
retry. A2UI rejection counts as a failed Tool without making an otherwise
successful Run fail.

Logs are best-effort observations, not recovery state. An ungraceful process
loss can leave an accepted event without a terminal event; startup marks the
existing durable Run interrupted, but does not reconstruct history from logs
or invent missing usage. Evaluate completeness separately from model failure
rate. Deleting Chat deletes Agent content only, never Core Research, Batch,
Result or DailyTrack data. No telemetry table or cascade exists.
The asynchronous stderr descriptor writer consumes write failures (including
broken pipes) without terminating product execution or logging its own error.

Native Mastra/MCP loggers stay silent, CopilotKit telemetry is disabled, and
the pinned AG-UI bridge's direct raw warnings are removed by the reproducible
pnpm patch documented in `tooling/patches/README.md`. Never turn on framework payload
tracing or print raw exceptions for diagnosis.

`pnpm test:e2e` includes the final-image privacy scenario. Thirteen distinct
fixture categories cover messages, system instructions, research inputs,
A2UI, MCP arguments/results, cookies, tokens, provider credentials/errors and
paths. The runner scans original Agent/Auth/Core/Caddy/Worker logs and test
diagnostics, including compressed traces and HTML-embedded report ZIPs,
**before** sanitization. A
leak fails an otherwise passing command. Retained reports contain only safe
file/service labels and hit categories; redaction cannot change that outcome.

The explicit fake-provider scenario and its canary instruction are used only
with the registered Scripted Provider. They never modify real-model prompts.
Real-model quality evaluation remains a separate, explicitly invoked workflow.
