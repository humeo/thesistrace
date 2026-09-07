# ThesisTrace

ThesisTrace is a single-node, invite-only multi-user workspace for reproducible,
post-close A-share factor research, strategy backtesting, and daily tracking.

The active implementation is the module-first Core described in
[`docs/architecture/core.md`](docs/architecture/core.md).
Current product language is defined in [`CONTEXT.md`](CONTEXT.md), and accepted
decisions are grouped in the [ADR index](docs/adr/README.md).

## Repository layout

- `apps/core`: Python Core, module tests, benchmarks, `pyproject.toml`, `uv.lock`,
  and the shared API/Worker Dockerfile.
- `apps/web`, `apps/auth`, `apps/agent`: each application's source, tests,
  configuration, package manifest, and Dockerfile.
- `packages/contracts`: the explicit `@thesistrace/contracts` workspace package
  used by Web and Agent.
- `deploy`: Compose topology and overlays, Caddy configuration, and PostgreSQL
  initialization.
- `tooling`: configuration, development lifecycle, test orchestration, and
  dependency patches.
- `tests`: cross-application E2E, final-image checks, and shared fixtures.
- `docs`: architecture, decisions, and operating instructions.

The root `package.json` provides the supported project commands. Application
dependencies belong in their own manifests; the root owns cross-application test
tools. Install JavaScript dependencies once from the root with the shared pnpm
lockfile. Python dependencies use `uv sync --project apps/core --frozen`.

## Local development

Install [mise](https://mise.jdx.dev/), [uv](https://docs.astral.sh/uv/), and
Docker with Compose support. Then install the pinned Node.js and pnpm versions,
sync host dependencies, validate Compose, and build the local images:

Runtime settings and credentials come from the private repository-root `.env`.
The tracked `.env.example` contains no secrets. Create a local configuration,
fill its external service credentials, then validate and build:

```sh
mise install
mise exec -- pnpm config:init
# Edit .env: Resend sender/key, Tushare token, and enabled model provider keys.
mise exec -- pnpm config:check
mise exec -- pnpm bootstrap
```

`config:init` generates local database, object-store, Auth, and MCP signing
credentials once and refuses to overwrite an existing file. Model definitions
remain in `apps/agent/config/model-registry.json`; set the canonical provider key and
`THESISTRACE_AGENT_OPENAI_BASE_URL` in `.env` for your chosen endpoint.
See the [configuration guide](docs/runbook/configuration.md) for the complete
configuration inventory, Production settings, and private CLI commands.

Start the complete Development topology with Compose Watch:

```sh
mise exec -- pnpm dev
```

Open `http://127.0.0.1:5173`. Caddy Web, Hono and Better Auth, Agent, FastAPI Core,
the ordinary Research, Batch Research, Tracking, and Data Operator Workers,
PostgreSQL, RustFS, and the three one-shot schema initializers belong to the canonical
Compose project. There is no public signup; Researcher invitation and access
commands are documented for [local Development](docs/runbook/local-lifecycle.md#local-researcher-access)
and [single-node Production](docs/runbook/single-node-production.md#operator-assignment-and-researcher-access).
For a detached start use `mise exec -- pnpm dev:up`; use
`mise exec -- pnpm dev:stop` to stop services without deleting data, and
`mise exec -- pnpm dev:reset` to hard-cut Product State while preserving Canonical
Data. Use `mise exec -- pnpm dev:erase` only when all Development data should be
deleted.

The complete Development command contract, Test isolation rules, and failure
evidence are documented in the [local lifecycle guide](docs/runbook/local-lifecycle.md).
The canonical single-node Production wrapper, external environment contract,
and Researcher access operations are documented in the
[Production runbook](docs/runbook/single-node-production.md). Passing local
checks qualifies the images and configuration; it does not assert that any
particular Production deployment is healthy.

Canonical market data is prepared outside the user product through the
[private Data Operator](docs/runbook/data-operator.md). The Data page is a
read-only view of the current Dataset Head.

The current Tushare adapter has a separate
[credential verification guide](docs/runbook/tushare-live-bootstrap.md).

Run the current backend, frontend, and browser acceptance checks with:

```sh
mise exec -- pnpm check
```

Before a release, include the final Production Image Smoke with:

```sh
mise exec -- pnpm check:release
```

Agent model quality additionally requires the separate, authorized
[real-model evaluation](docs/runbook/research-agent-eval.md). Deterministic
release checks alone do not qualify a Provider/model/reasoning combination.

Run the long-Research final-image performance qualification separately on a
controlled idle host:

```sh
mise exec -- pnpm check:performance
```
