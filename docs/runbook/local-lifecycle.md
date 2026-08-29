# Local Development and Test lifecycle

Development is one persistent canonical Compose project. Each Test command
creates a new, isolated, disposable Compose project. Both run the same
Caddy/Auth/Core/Worker route graph used by the single-node Production topology,
with loopback ports and disposable Test mail replacing the external edge.
Local evidence qualifies code, images, and configuration; it is not a health
claim about any deployed host. The deployment contract is in the
[single-node Production runbook](single-node-production.md).

## Prerequisites and bootstrap

Install mise, uv, and Docker with Compose Watch support. The repository pins
Node.js 24.14.0 and pnpm 11.9.0 in `.mise.toml`; uv owns the Python environment
and lock-file sync. Run bootstrap from the repository root:

```sh
mise install
mise exec -- pnpm bootstrap
```

Bootstrap runs frozen Python and pnpm dependency sync, validates the resolved
Compose configuration, pulls PostgreSQL and RustFS, and builds the Core, Auth,
and Caddy Web application images. It changes no Development database and
publishes no Seed data.

The examples below keep `mise exec --` explicit so that the pinned Node.js and
pnpm versions are used even when shell activation is not configured.

## Development

The foreground edit loop uses Compose Watch:

```sh
mise exec -- pnpm dev
```

Web and Auth changes rebuild their image, API changes reload Uvicorn, changes
under `src/` restart all three fixed-role Workers, and dependency manifest
changes rebuild the affected image. Pressing Ctrl-C exits the foreground command
without deleting Development volumes.

Development runs one `research-worker`, one `batch-research-worker`, and one
`tracking-worker`. Each process has one execution slot, 2 vCPU, 2 GiB hard
memory, a 1.5-GiB execution-planning budget, and at most two calculation
threads. Role-specific Compose variables can change capacity independently; a
process never adds a second execution slot or switches roles.

For a background runtime that waits for health:

```sh
mise exec -- pnpm dev:up
```

Open the product at `http://127.0.0.1:5173`. Follow all service logs in another
terminal with:

```sh
mise exec -- pnpm dev:logs
```

This streams current Caddy Web, Auth, API, all three Workers, both schema
initializers, PostgreSQL, and RustFS container output. A Data Operator or
Auth Operator invocation writes its machine-readable result to that command's
stdout and operational JSONL to its stderr, so its current output is visible in
the invoking terminal without mixing the two streams.

Compose uses Docker's `json-file` driver for every managed service with
`max-size=10m` and `max-file=3`. The bytes live in Docker-managed container
storage, not in this repository; no application log directory exists. Ordinary
`dev:stop` preserves the current containers and their available log history.
Rotation discards older files, while container recreation/deletion,
`dev:reset`, and `dev:erase` can remove the associated history. These logs are
short-lived diagnostic evidence, not an audit trail or permanent archive.

Each event is one JSON object with `timestamp`, `level`, `component`, and
`event`. Depending on the boundary it may also carry `operation_id`, `run_id`,
`track_id`, `attempt_id`, or `http_request_id`. `INFO` is normal progress,
`WARNING` is retryable degradation or an actionable blocked state, and `ERROR`
is an unexpected or terminal internal failure. Health traffic and idle Worker
polls are intentionally quiet.

Check process liveness and dependency readiness separately:

```sh
curl -fsS http://127.0.0.1:8100/health/live
curl -fsS http://127.0.0.1:8100/health/ready
```

These direct API ports are Development-only diagnostics; Caddy returns `404`
for public `/health/*` and `/internal/*`. Core liveness checks only that the API
can serve. Core readiness checks Auth, PostgreSQL, RustFS, and readability of
the mounted Dataset root under a bounded deadline. Auth readiness checks its
database, exact schema fingerprint, and Session storage. Neither readiness
contract inspects Worker capacity, queue depth, Dataset coverage, Results, or
Tracking Checkpoints. Compose restarts API and Auth from dependency-free
liveness rather than dependency readiness.

## Local Researcher access

Development has no public signup. Before `pnpm dev` or `pnpm dev:up`, ensure
the current shell exports the already-configured `RESEND_API_KEY` and
`RESEND_FROM_EMAIL`; shell values override the non-Production values in
`deploy/core/dev.env`. Development sends real invitation and reset mail, while
all automated tests use the private local fake.

Issue the first 48-hour invitation from the canonical Development project:

```sh
mise exec -- docker compose \
  --project-name thesistrace-dev \
  --env-file deploy/core/dev.env \
  --file deploy/core/compose.yaml \
  --file deploy/core/compose.dev.yaml \
  run --rm --no-deps -T auth \
  node dist/operator.js invite --email researcher@example.com
```

The command prints an Invitation ID but never the token or link. Resend delivers
the fragment-bearing link, and the Researcher supplies only a password on the
acceptance page. Reissue and the remaining private access operations use the
same Auth command contract documented in the
[Production runbook](single-node-production.md#researcher-access-operations).

Inspect authoritative Product State without RustFS or the Dataset Store:

```sh
mise exec -- docker compose --project-name thesistrace-dev \
  --env-file deploy/core/dev.env \
  --file deploy/core/compose.yaml \
  --file deploy/core/compose.dev.yaml \
  run --rm --no-deps -T initialize \
  thesistrace-core-diagnose research-run RESEARCHER_ID RUN_ID

mise exec -- docker compose --project-name thesistrace-dev \
  --env-file deploy/core/dev.env \
  --file deploy/core/compose.yaml \
  --file deploy/core/compose.dev.yaml \
  run --rm --no-deps -T initialize \
  thesistrace-core-diagnose daily-track RESEARCHER_ID TRACK_ID
```

Both commands print one stable JSON snapshot to stdout. Exit code 3 means not
found and 4 means PostgreSQL/query unavailable. The snapshot is read-only;
PostgreSQL remains the sole authority for lifecycle, leases, retry, recovery,
publication, and Checkpoints. There is no local dashboard, alert, or log search
service in this capability.

Stop the services while preserving PostgreSQL and RustFS data:

```sh
mise exec -- pnpm dev:stop
```

Running `dev:up` again restores the same Development resources. Reset is the
ordinary Product State hard-cut command:

```sh
mise exec -- pnpm dev:reset
```

Reset accepts only the canonical `thesistrace-dev` project, deletes and
recreates its PostgreSQL, RustFS, and Batch Attempt Control runtime volumes,
including Core Product State and Auth state. It preserves the canonical-data
volume and exact Dataset Head, runs both one-shot schema initializers, and waits
for health. It does not contact Tushare, migrate old Product State, or publish
Fixture data. The initialized runtime validates and immediately reuses the
preserved mounted Canonical Data Store.

Complete deletion of Product State and downloaded Canonical Data is a separate
explicit operation:

```sh
mise exec -- pnpm dev:erase
```

`dev:erase` accepts only the canonical `thesistrace-dev` project, stops it, and
removes all four Development volumes without restarting the runtime. Research
cannot run again until Canonical Data is bootstrapped or restored.

## Test gates

Run the inexpensive host checks first during ordinary edits:

```sh
mise exec -- pnpm test
```

Run real PostgreSQL, Auth-schema, and RustFS integration and acceptance tests in
a fresh Test project:

```sh
mise exec -- pnpm test:integration
```

Run host Playwright against a fresh complete Caddy/Auth/API/fixed-role
Workers/PostgreSQL/RustFS topology with a private Resend-compatible fake:

```sh
mise exec -- pnpm test:e2e
```

The browser gate sends every request through Caddy and uses two Researchers to
cover Invitation acceptance/replay/expiry/reissue, login/logout/reset/password
change, Session revocation, deactivate/reactivate, bootstrap retry, Auth
unavailability, CSP compatibility, and Folder/Run/Batch/Track/receipt/cursor/
Draft isolation.

Qualify the built Core, Auth, and Caddy Web images against a prepared Canonical
Data mount on an internal-only Compose network:

```sh
mise exec -- pnpm test:image-smoke
```

The image smoke initializes fresh Core and Auth schemas, prepares deterministic
mounted data, and executes ordinary Research, both Research Batch Kinds, and
Tracking through the three real fixed-role Workers. It compares Batch Results
and elapsed time with strictly serial ordinary Runs, exercises Batch cancellation, restarts
API, PostgreSQL, RustFS, the mounted Dataset root, and all Workers at their real
boundaries, and verifies the same Head, Results, Batch history, readiness, and
Attempts remain authoritative. It executes both packaged PostgreSQL-only
diagnostic commands, validates API, ResearchRun, Research Batch, DailyTrack, and
Data Refresh events, and scans collected evidence for secret canaries. It also
rejects capacity declarations above actual cgroup limits and records structured
Worker events, image identity, timing, RSS, object bytes, health/exit state,
network isolation, and Product State before and after cleanup under the run
evidence directory. Its Caddy segment uses the same Production Caddyfile with a
test-only internal CA and `.test` hostname to prove HTTP-to-HTTPS redirect,
HSTS, private-path rejection, trusted header overwrite, sanitized logs, and
persistent certificate state without reaching the public internet.

Publication uses one S3 request attempt with a five-second connect/read bound.
The bound covers observed immutable Result uploads under the full long-range
qualification load; it does not retry, fall back, or turn a failed publication
into a successful Run.

Before merge, run the standard fail-fast gate:

```sh
mise exec -- pnpm check
```

`pnpm check` delegates to `pnpm test`, `pnpm test:integration`, and
`pnpm test:e2e` in that order. A failing layer returns non-zero and prevents
later layers from starting. Integration and browser commands use random
loopback ports, distinct `thesistrace-test-*` project identities, separate
volumes, and isolated object-store buckets. They never address or clean
`thesistrace-dev`.

Before a release, run every local seam, including the final image qualification:

```sh
mise exec -- pnpm check:release
```

`pnpm check:release` runs `pnpm check` once, then `pnpm test:image-smoke`, then
the dual-kind `pnpm test:benchmark` final-image qualification. It does not
repeat the standard gate.

## Evidence, cleanup, and interactive diagnosis

Each Test run records metadata and artifacts under
`.local/test-runs/<run-id>/`. `run.txt` binds the run identity to its exact
Compose project and records the Git revision/dirty state, ports, each named
phase's elapsed seconds and status, cleanup status, and final status. Available
evidence includes JUnit XML or the Playwright HTML report and failure artifacts.
When a Test fails, the runner also captures Compose status, timestamped logs,
and container inspection before cleanup.

Success always removes the Test containers, network, and volumes. Failure does
the same by default after evidence capture. To keep only a failing environment
for interactive inspection, append the diagnostic escape hatch:

```sh
mise exec -- pnpm test:integration --keep-environment
mise exec -- pnpm test:e2e --keep-environment
```

The command prints the exact Test project name. After inspection, clean that
project through its metadata-bound safety check:

```sh
THESISTRACE_TEST_PROJECT_NAME=thesistrace-test-<run-id> \
  mise exec -- pnpm test:cleanup
```

The keep option has no effect on a successful run. Cleanup refuses Development,
malformed Test identities, and Test identities without matching `run.txt`
metadata.

## Local change workflow

Use Local Markdown Specs and Issues under `.scratch/` for non-trivial work; keep
small bounded fixes proportional and avoid unnecessary planning files. Work on
a short-lived feature, fix, or chore branch and implement vertically through the
public product or lifecycle seam.

Run focused checks during implementation, the relevant real-service milestone
gate when behavior crosses Compose, and `mise exec -- pnpm check` before merge.
Complete local Standards and Spec review against a fixed point, resolve its
findings, then fast-forward the verified branch. A GitHub Pull Request may be
used for collaboration, but it is not a required gate in the current local-only
phase.
