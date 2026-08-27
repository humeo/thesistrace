# Research Agent MCP V1 contract

The Research Agent exposes one hard-cut MCP contract through packaged stdio and
the current stateless Streamable HTTP `/mcp` endpoint. V1 has exactly 18 tools
and six scopes. The default local stdio authority has the four non-destructive
read and execute scopes, so it discovers 15 tools. Research cancellation and
DailyTrack Stop are present only when their independent scopes are explicitly
enabled. The registry rechecks the effective authority on every call.

MCP is a bounded adapter over Core services. It does not own a User, tenant,
Workspace, quota, billing, Campaign, execution, recovery, or protocol-session
resource. It does not expose Prompts, Resources, Sampling, Elicitation,
Subscriptions, generic code or network execution, object-storage access, or
operator functions. Durable ResearchRun, Research Batch, and DailyTrack state
remains the recovery truth after a connection closes.

## Fixed ingress envelope

These V1 constants are product code, not deployment or caller configuration:

| Boundary | Fixed V1 value |
| --- | ---: |
| Raw or canonical tool-call request | 131,072 bytes |
| Tool discovery or tool-call response | 262,144 bytes |
| Formula | 4,096 characters |
| Calls per principal per fixed window | 120 per 60 seconds |
| Active calls per principal | 4 |
| List default / maximum | 20 / 50 items |
| Batch maximum | 20 items |
| Catalog identifier maximum | 50 items |
| Opaque cursor | 1,024 characters |

Authentication and raw HTTP request size are checked before MCP dispatch.
Canonical request size, Schema, deployment allowlist, scope, rate, and
concurrency are checked before a tool handler can reach PostgreSQL, RustFS, or
Worker admission. Core capacity and lifecycle admission remain authoritative.
An over-limit response is replaced atomically with a bounded structured error;
it is never truncated or partially returned.

## Deterministic sizing evidence

The inventory test serializes each tool name, required scope, description,
annotations, input Schema, and output Schema with sorted JSON keys. Its current
V1 SHA-256 is
`96cebd400bb6893eaa8be98de2737122d35d1b8cb938257ce288454b63ab65b0` and
the canonical inventory is 143,094 bytes. A maximum 20-item Factor Evaluation
Batch with a 4,096-character Formula in every item serializes to 84,536 bytes,
so it fits the request ceiling without weakening either collection bound.

The ceiling leaves deterministic protocol overhead above those observed
payloads while remaining small relative to the current 2-vCPU, 2-GiB
single-slot production Worker envelope and its 1.5-GiB execution-planning
budget. The reproducible command, envelope, and observed CPU/RSS evidence are
recorded in
[`research-agent-mcp-v1-ingress-benchmark.json`](../research/research-agent-mcp-v1-ingress-benchmark.json).
That probe completed the inventory, 120-call window, and four-call concurrency
tests in 1.98 seconds of pytest time, with 151,650,304 bytes maximum RSS (7.06
percent of the 2-GiB container envelope) and no swap. Tests pin the constants,
inventory fingerprint, observed byte sizes, oversized single-item behavior,
rate isolation, and concurrent-call admission. Any contract change is a hard
cut that must update this evidence and the exact inventory test together; V1
has no alias, compatibility dispatcher, or fallback path.
