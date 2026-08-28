# ThesisTrace

ThesisTrace is a single-node workspace for reproducible, post-close A-share
factor research, strategy backtesting, and daily tracking.

The active implementation is the module-first Core described in
[`docs/architecture/core.md`](docs/architecture/core.md).
Current product language is defined in [`CONTEXT.md`](CONTEXT.md), and accepted
decisions are grouped in the [ADR index](docs/adr/README.md).

## Local development

Install [mise](https://mise.jdx.dev/), [uv](https://docs.astral.sh/uv/), and
Docker with Compose support. Then install the pinned Node.js and pnpm versions,
sync host dependencies, validate Compose, and build the local images:

```sh
mise install
mise exec -- pnpm bootstrap
```

Start the complete Development topology with Compose Watch:

```sh
mise exec -- pnpm dev
```

Open `http://127.0.0.1:5173`. Web, API, the fixed-role ordinary Research, Batch
Research, and Tracking Workers, PostgreSQL, RustFS, and the one-shot schema
initializer all belong to the canonical Compose project. For a
detached start use `mise exec -- pnpm dev:up`; use
`mise exec -- pnpm dev:stop` to stop services without deleting data, and
`mise exec -- pnpm dev:reset` to hard-cut Product State while preserving Canonical
Data. Use `mise exec -- pnpm dev:erase` only when all Development data should be
deleted.

The complete command contract, Test isolation rules, and failure evidence are
documented in the [local lifecycle guide](docs/runbook/local-lifecycle.md).
Only local Development and local Test exist today. Local checks are not
Production readiness.

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

Run the long-Research final-image performance qualification separately on a
controlled idle host:

```sh
mise exec -- pnpm check:performance
```
