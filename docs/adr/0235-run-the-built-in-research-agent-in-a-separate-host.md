# Run the built-in Research Agent in a separate Host

A private Agent Host owns model orchestration and durable Chat interaction while Core alone owns accepted Research execution and results. Mastra and CopilotKit supply the model and streaming integration, while ThesisTrace persists Turn controls, command receipts, and conversation projections; this separates conversation recovery from deterministic research recovery at the cost of an additional service. The Host obtains Research capabilities from Core MCP and has no direct access to Core, Auth, or Canonical data stores.

Transient main-model failures retry the unfinished model step at most twice
(three attempts total). Mastra's `StreamErrorRetryProcessor` owns abortable
backoff: 1 second, then 2 seconds, honoring bounded provider `Retry-After`.
The allowance resets after a successful model step. Authentication, invalid
requests, refusal, malformed completion, and exhausted account quota do not
retry. Context/output-limit recovery keeps its separate existing allowance.

`THESISTRACE_AGENT_PROVIDER_CALL_TIMEOUT_SECONDS` configures the individual
provider deadline, defaulting to 180 seconds. Each retry receives a new deadline;
the Run wall-time limit and explicit Stop still take precedence. Earlier completed
tool/result pairs remain in model context and are not executed again by retry.
Unfinished response text is replaced in model history and the browser timeline.
Tool invocations are held until a valid completion; a transport error after that
completion cannot replay those released calls. Every actual provider request is
metered separately, retaining unknown-usage reservations on failed attempts.
