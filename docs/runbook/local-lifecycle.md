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
images. It migrates no Development database and publishes no Seed data.

The examples below keep `mise exec --` explicit so that the pinned Node.js and
pnpm versions are used even when shell activation is not configured.

## Development

The foreground edit loop uses Compose Watch:

```sh
mise exec -- pnpm dev
```

Web changes are synchronized for Vite HMR, API changes reload Uvicorn, Worker
changes restart the Worker, and dependency manifest changes rebuild the
affected image. Pressing Ctrl-C exits the foreground command without deleting
Development volumes.

For a background runtime that waits for health:

```sh
mise exec -- pnpm dev:up
```

Open the product at `http://127.0.0.1:5173`. Follow all service logs in another
terminal with:

```sh
mise exec -- pnpm dev:logs
```

Stop the services while preserving PostgreSQL and RustFS data:

```sh
mise exec -- pnpm dev:stop
```

Running `dev:up` again restores the same Development resources. Reset is the
only normal destructive Development command:

```sh
mise exec -- pnpm dev:reset
```

Reset accepts only the canonical `thesistrace-dev` project, deletes its volumes,
recreates the complete topology, runs the one-shot Migration service, and waits
for health. It does not publish Fixture data or any other Seed; the first
Dataset Release must still come from the Data Update product action.

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

Run host Playwright against a fresh complete Web/API/Worker/PostgreSQL/RustFS
topology:

```sh
mise exec -- pnpm test:e2e
```

Before merge, run the complete fail-fast gate:

```sh
mise exec -- pnpm check
```

`pnpm check` delegates to `pnpm test`, `pnpm test:integration`, and
`pnpm test:e2e` in that order. A failing layer returns non-zero and prevents
later layers from starting. Integration and browser commands use random
loopback ports, distinct `thesistrace-test-*` project identities, separate
volumes, and isolated object-store buckets. They never address or clean
`thesistrace-dev`.

## Evidence, cleanup, and interactive diagnosis

Each Test run records metadata and artifacts under
`.local/test-runs/<run-id>/`. `run.txt` binds the run identity to its exact
Compose project and records ports, cleanup status, and final status. Available
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
