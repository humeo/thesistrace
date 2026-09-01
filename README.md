# ThesisTrace

ThesisTrace is a single-node, invite-only multi-user workspace for reproducible,
post-close A-share factor research, strategy backtesting, and daily tracking.

The active implementation is the module-first Core described in
[`docs/architecture/core.md`](docs/architecture/core.md).
Current product language is defined in [`CONTEXT.md`](CONTEXT.md), and accepted
decisions are grouped in the [ADR index](docs/adr/README.md).

## Local development

Install [mise](https://mise.jdx.dev/), [uv](https://docs.astral.sh/uv/), and
Docker with Compose support. Then install the pinned Node.js and pnpm versions,
sync host dependencies, validate Compose, and build the local images:

The Development Agent uses `gpt-5.6-luna` with `high` reasoning through the local
OpenAI-compatible service at `http://localhost:8317/v1`. Export the existing
`CLI_API_KEY` in the launching shell; Compose injects it only into Agent and
uses `host.docker.internal:8317` inside the container. No key value is stored in
the repository. Deterministic Test commands retain their isolated Scripted model.

```sh
export CLI_API_KEY
mise install
mise exec -- pnpm bootstrap
```

Start the complete Development topology with Compose Watch:

```sh
mise exec -- pnpm dev
```

Open `http://127.0.0.1:5173`. Caddy Web, Hono and Better Auth, FastAPI Core, the
fixed-role ordinary Research, Batch Research, and Tracking Workers, PostgreSQL,
RustFS, and the two one-shot schema initializers all belong to the canonical
Compose project. There is no public signup; Researcher invitation and access
commands are documented for [local Development](docs/runbook/local-lifecycle.md#local-researcher-access)
and [single-node Production](docs/runbook/single-node-production.md#researcher-access-operations).
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
