# Research Agent MCP V1 contract

The Research Agent exposes one hard-cut MCP contract through packaged stdio and
the current stateless Streamable HTTP `/mcp` endpoint. V1 has exactly 19 tools
and six scopes. The default local stdio authority has the four non-destructive
read and execute scopes, so it discovers 16 tools. Research cancellation and
DailyTrack Stop are present only when their independent scopes are explicitly
enabled. The registry rechecks the effective authority on every call.

MCP is a bounded adapter over Core services. It does not own a User, tenant,
Workspace, quota, billing, Campaign, execution, recovery, or protocol-session
resource. It does not expose Prompts, Resources, Sampling, Elicitation,
Subscriptions, generic code or network execution, object-storage access, or
operator functions. Durable ResearchRun, Research Batch, and DailyTrack state
remains the recovery truth after a connection closes.

## Connect an external AI client

Open **MCP** in the product sidebar at `/connections/mcp`. Copy the configured
Server URL, then use the English setup prompt or the displayed Codex / Claude
Code command. The client starts authorization in a browser, the Researcher signs
in to ThesisTrace and approves the requested permissions, and the client
retrieves the scope-filtered tool set. Copying instructions does not create an
authorization. Check connection performs MCP discovery without executing a tool
or calling a model.

Auth serves OAuth authorization-server metadata at
`/.well-known/oauth-authorization-server/api/auth` and
`/api/auth/.well-known/oauth-authorization-server`. Core serves the protected
resource metadata at `/.well-known/oauth-protected-resource/mcp`. The configured
issuer must be the public ThesisTrace origin followed by `/api/auth`; Production
requires HTTPS, while Development/Test allow loopback HTTP. The protocol URL
remains `/mcp` and is never a product HTML route.

External clients use authorization code + S256 PKCE and the `resource` parameter.
They may request the four read/execute scopes and `offline_access`; cancellation
and Stop scopes are not granted by this Auth provider. Access and refresh tokens
remain with the AI client, never in the website. Auth stores their hashes; Core
checks external access with the private Auth verifier on every request.

**Authorized apps** lists only the current Researcher's consent records. Revoke
access removes the app's pending authorization codes, access tokens, refresh
tokens and consent. Reauthorization starts again from the AI client. Authorization
does not indicate an active network connection, and the page does not claim a
last tool-use time. Expired token and assertion records are handled by Auth's
existing cleanup job. A fresh current Auth schema is required; startup verifies
its exact catalog and does not migrate an existing schema.

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
  "THESISTRACE_BENCHMARK_MOUNT",
  "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
  "THESISTRACE_RESEARCH_AGENT_RESEARCHER_ID",
]
required = true
startup_timeout_sec = 20
tool_timeout_sec = 90
default_tools_approval_mode = "approve"
```

The default stdio process binds the explicitly configured Researcher UUID to
the operational subject `local_operator` and discovers exactly 16 read/execute
tools. The UUID must identify a bootstrapped Researcher; there is no ownerless
or implicit default identity. It does not discover
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
`b011d1801f2dc5040f15519cfbef609c6dfdaaca3827732bb33f43d1e18ee32e` and
the canonical inventory is 151,707 bytes. A maximum 20-item Factor Evaluation
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

## Read bounded pages and operation receipts

List and collection pages default to 20 records, at most 50. Each model-facing
business JSON page, including metadata and its continuation cursor, is at most
32 KiB in UTF-8. A page can contain fewer than the requested number of records;
follow `next_cursor` until it is null. Fields and financial numbers in each
returned record remain complete. This is separate from the 256 KiB MCP wire
response and 512 KiB Agent decoded-response guards.

`get_alpha_catalog` counts fields and builtins together, ordered by category
(fields first) and then identifier. For example:

```json
{"identifiers":["close","rank","ts_mean"],"limit":2}
```

Pass the returned cursor as `cursor` with the same identifier filter for the next
page. Omitting `identifiers` traverses the whole catalog. Catalog text and array
length limits are declared in the tool's JSON Schema; unknown identifiers are
reported explicitly.

`get_research_context` returns one folder page alongside Data Overview and
authoring constraints. Continue with `folder_cursor` from `folders.next_cursor`,
and use `folder_limit` to choose the page size. Folder names retain the declared
120-character domain limit. Do not interpret the first folder page as all folders.

Catalog and folder cursors are authenticated and bind the Researcher, query and
collection version. If the collection changes, start a new traversal. Result
cursors retain their identity, query and immutable Result/snapshot binding.
ResearchRun and DailyTrack collection sections continue through
`get_research_run_result` and `get_daily_track_result`; summary metrics are returned
in full and never paraphrased into numeric substitutes.

Accepted writes return small receipts containing the durable resource ID, status,
replay flag, retry interval where applicable, and `next_tool`. Cancellation does
not embed the Run or Batch detail. Call the indicated read tool to inspect the
resource. A later read or Agent failure does not reverse a successful operation;
keep the existing resource/request identity rather than submitting it again.

Research notes (`hypothesis`) accept at most 1,024 Unicode characters for both
single-run and batch admission. The same bound is declared on frozen inputs and
Result provenance; formulas remain limited to 4,096 characters. Longer notes are
rejected before admission rather than silently shortened. The authoring form
shows the notes count and prevents submission above the limit.
