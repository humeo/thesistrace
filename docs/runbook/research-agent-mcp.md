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

## Local Codex stdio configuration

Install the project package, then register the packaged entrypoint in a trusted
Codex project configuration. Forward only the names of the existing Core
runtime variables; do not copy their values into the configuration file.

```toml
[mcp_servers.thesistrace]
command = "thesistrace-research-agent-mcp"
cwd = "/absolute/path/to/thesistrace"
env_vars = [
  "THESISTRACE_DATABASE_URL",
  "THESISTRACE_S3_ENDPOINT_URL",
  "THESISTRACE_S3_ACCESS_KEY_ID",
  "THESISTRACE_S3_SECRET_ACCESS_KEY",
  "THESISTRACE_S3_BUCKET",
  "THESISTRACE_S3_REGION",
  "THESISTRACE_DATA_MOUNT",
  "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
]
required = true
startup_timeout_sec = 20
tool_timeout_sec = 90
default_tools_approval_mode = "approve"
```

The default stdio process binds `local_operator` without login and discovers
exactly 15 read/execute tools. It does not discover
`cancel_research_run`, `cancel_research_batch`, or `stop_daily_track`.
Enabling a dangerous scope is an explicit per-process operator decision; Host
approval metadata is additional UX protection and never replaces the server's
scope check.

Run the explicit real-Host acceptance only after approving transmission of the
isolated Fixture research context and bounded semantic MCP results to the
configured Codex provider:

```sh
pnpm test:codex-mcp
```

The command owns a uniquely named Compose project, PostgreSQL database, RustFS
bucket, data mount, and evidence directory. It configures two ephemeral
`codex exec` processes with user config and project rules disabled. The first
process discovers the safe inventory, reads authoring context, corrects an
invalid Formula, submits a ResearchRun, and disconnects while it remains
queued. The second process reconnects by durable `run_id`, starts the real
Worker after its first poll, waits for the terminal state, and reads the
strategy summary plus two cursor pages. The harness disables Codex shell,
unified execution, browser, computer-use, code-mode, app, image-generation,
JavaScript-REPL, and multi-agent features. The Host receives a minimal process
environment without any `THESISTRACE_*` value; the disposable Core values are
stored in a mode `0600` run-local file read only by an ephemeral MCP launcher,
so neither the Host environment nor its process arguments contain credentials.
The launcher and secret file are removed when each Host process exits. The
event ledger fails closed if Codex uses any non-MCP execution item or a product
HTTP, SQL, file, or internal Python path. JSONL line, event, transcript, and
stderr byte limits plus a small final-output ceiling terminate a noisy or
malformed Host process group rather than accumulating unbounded diagnostics.
Failure evidence maps unknown Host event types, Tool fields, and diagnostic
codes to a fixed `unknown` category. The real-Host command does not emit a raw
JUnit report, and its terminal failure is reduced to a fixed error code so
pytest output cannot reproduce dynamic Formula, hypothesis, or cursor values.

Run-local evidence is written to
`.local/test-runs/<run-id>/evidence/codex-stdio-acceptance.json` and includes the
Host configuration summary, exact discovered tool names, durable ID and status
trace, pagination boundary, bounded conclusion, MCP trace IDs, and component
versions. The conclusion uses three closed categorical fields rather than free
prose. Before writing success evidence, the harness scans the exact Formula,
hypothesis, cursor, position/instrument, and private storage canaries observed
in the in-memory Tool ledger. It contains neither those values nor credential
values. This acceptance proves
only local Codex over stdio; it does not validate a second Host, production
OAuth, or public Cloudflare deployment.

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
`2b8cc6a48f5df6815a41eeb054973f1b82ac0da8536c088899249d4904dc7952` and
the canonical inventory is 143,238 bytes. A maximum 20-item Factor Evaluation
Batch with a 4,096-character Formula in every item serializes to 84,536 bytes,
so it fits the request ceiling without weakening either collection bound.

The ceiling leaves deterministic protocol overhead above those observed
payloads while remaining small relative to the current 2-vCPU, 2-GiB
single-slot production Worker envelope and its 1.5-GiB execution-planning
budget. The reproducible command, envelope, and observed CPU/RSS evidence are
recorded in
[`research-agent-mcp-v1-ingress-benchmark.json`](../research/research-agent-mcp-v1-ingress-benchmark.json).
That probe completed the inventory, 120-call window, and four-call concurrency
tests in 2.08 seconds of pytest time, with 153,223,168 bytes maximum RSS (7.14
percent of the 2-GiB container envelope) and no swap. Tests pin the constants,
inventory fingerprint, observed byte sizes, oversized single-item behavior,
rate isolation, and concurrent-call admission. Any contract change is a hard
cut that must update this evidence and the exact inventory test together; V1
has no alias, compatibility dispatcher, or fallback path.
