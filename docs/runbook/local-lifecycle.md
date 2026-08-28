# Local Development and Test lifecycle

ThesisTrace currently has only local Development and local Test. Development
is one persistent canonical Compose project. Each Test command creates a new,
isolated, disposable Compose project. Local evidence is not Production readiness.
This lifecycle defines no remote environment or release process.

## Prerequisites and bootstrap

Install mise, uv, and Docker with Compose Watch support. The repository pins
Node.js 24.14.0 and pnpm 11.9.0 in `.mise.toml`; uv owns the Python environment
and lock-file sync. Run bootstrap from the repository root:

```sh
mise install
mise exec -- pnpm bootstrap
```

Bootstrap runs frozen Python and pnpm dependency sync, validates the resolved
Compose configuration, pulls PostgreSQL and RustFS, and builds the application
images. It changes no Development database and publishes no Seed data.

The examples below keep `mise exec --` explicit so that the pinned Node.js and
pnpm versions are used even when shell activation is not configured.

## Development

The foreground edit loop uses Compose Watch:

```sh
mise exec -- pnpm dev
```

Web changes are synchronized for Vite HMR, API changes reload Uvicorn, Worker
changes restart both fixed-role Workers, and dependency manifest changes rebuild
the affected image. Pressing Ctrl-C exits the foreground command without deleting
Development volumes.

Development runs one `research-worker` and one `tracking-worker`. Each process has
one execution slot, 2 vCPU, 2 GiB hard memory, a 1.5-GiB execution-planning budget,
and at most two calculation threads. The role-specific Compose variables can change
capacity independently, and Compose `--scale research-worker=N` or
`--scale tracking-worker=N` changes concurrency by replica count; a process never
adds a second execution slot or switches roles.

For a background runtime that waits for health:

```sh
mise exec -- pnpm dev:up
```

Open the product at `http://127.0.0.1:5173`. Follow all service logs in another
terminal with:

```sh
mise exec -- pnpm dev:logs
```

This streams current API, Research Worker, Tracking Worker, schema initializer,
PostgreSQL, RustFS, and Web container output. A Data Operator invocation writes
its machine-readable result to that command's stdout and operational JSONL to
its stderr, so its current output is visible in the invoking terminal without
mixing the two streams.

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

Liveness checks only that the API can serve. Readiness checks PostgreSQL,
RustFS, and readability of the mounted Dataset root under a bounded deadline.
It does not inspect Worker capacity, queue depth, Dataset coverage, bootstrap
completion, Results, or Tracking Checkpoints. Compose continues to restart the
API from liveness rather than dependency readiness.

Inspect authoritative Product State without RustFS or the Dataset Store:

```sh
mise exec -- docker compose --project-name thesistrace-dev \
  --env-file deploy/core/dev.env \
  --file deploy/core/compose.yaml \
  --file deploy/core/compose.dev.yaml \
  run --rm --no-deps -T initialize \
  thesistrace-core-diagnose research-run RUN_ID

mise exec -- docker compose --project-name thesistrace-dev \
  --env-file deploy/core/dev.env \
  --file deploy/core/compose.yaml \
  --file deploy/core/compose.dev.yaml \
  run --rm --no-deps -T initialize \
  thesistrace-core-diagnose daily-track TRACK_ID
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

Reset accepts only the canonical `thesistrace-dev` project, deletes and recreates
its PostgreSQL, RustFS, and Batch Attempt Control runtime volumes, preserves the
canonical-data volume and exact Dataset Head, and preserves the independent
benchmark-data volume and its current Snapshot. It then runs the one-shot
schema initializer and waits for health. It does not contact Tushare, migrate
old Product State, or publish Fixture data. The initialized runtime validates
and immediately reuses the preserved mounted Canonical Data Store; Benchmark
readiness is reported independently through Data Overview.

Complete deletion of Product State, downloaded Canonical Data, and the
Benchmark Snapshot is a separate explicit operation:

```sh
mise exec -- pnpm dev:erase
```

`dev:erase` accepts only the canonical `thesistrace-dev` project, stops it, and
removes all five Development volumes without restarting the runtime. Research
cannot run again until Canonical Data is bootstrapped or restored; the next
Market Bootstrap recreates the Benchmark Snapshot before the first Head.

## Test gates

Run the inexpensive host checks first during ordinary edits:

```sh
mise exec -- pnpm test
```

Run real PostgreSQL and RustFS integration and acceptance tests in a fresh Test
project:

```sh
mise exec -- pnpm test:integration
```

Run host Playwright against a fresh complete Web/API/fixed-role
Workers/PostgreSQL/RustFS topology:

```sh
mise exec -- pnpm test:e2e
```

Qualify the built Backend and Nginx Web images against a prepared Canonical
Data mount on an internal-only Compose network:

```sh
mise exec -- pnpm test:image-smoke
```

The image smoke initializes a fresh database, prepares deterministic mounted
data, and executes ordinary Research, both Research Batch Kinds, and Tracking
through the three real fixed-role Workers. It compares Batch Results and elapsed
time with strictly serial ordinary Runs, exercises Batch cancellation, restarts
API, PostgreSQL, RustFS, the mounted Dataset root, and all Workers at their real
boundaries, and verifies the same Head, Results, Batch history, readiness, and
Attempts remain authoritative. It executes both packaged PostgreSQL-only
diagnostic commands, validates API, ResearchRun, Research Batch, DailyTrack, and
Data Refresh events, and scans collected evidence for secret canaries. It also
rejects capacity declarations above actual cgroup limits and records structured
Worker events, image identity, timing, RSS, object bytes, health/exit state,
network isolation, and Product State before and after cleanup under the run
evidence directory.

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

`pnpm check:release` runs `pnpm check` once and then `pnpm test:image-smoke`. It
does not repeat the standard gate or run the long performance qualification.

Run the dual-kind long-Research performance qualification separately, only on
a controlled and otherwise idle host:

```sh
mise exec -- pnpm check:performance
```

The command keeps one serial Research Worker and five fresh cold plus five fresh
warm samples per Research Kind. It stores each completed sample and its verdict
before enforcing duration, memory, and first-Checkpoint limits, so a sample that
makes the maximum-of-five limit impossible stops the run immediately. Use this
gate for performance-sensitive Kernel, Data, Worker, or final-image changes and
for deliberate periodic qualification, not for ordinary merges.

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
