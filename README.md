# ThesisTrace

ThesisTrace is a single-node workspace for reproducible, post-close A-share
factor research, strategy backtesting, and daily tracking.

The active implementation is the module-first Core described in
[`docs/architecture/core.md`](docs/architecture/core.md).

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

Open `http://127.0.0.1:5173`. Web, API, Worker, PostgreSQL, RustFS, and the
one-shot Migration service all belong to the canonical Compose project. For a
detached start use `mise exec -- pnpm dev:up`; use
`mise exec -- pnpm dev:stop` to stop services without deleting data, and
`mise exec -- pnpm dev:reset` only when the Development data should be erased.

The complete command contract, Test isolation rules, and failure evidence are
documented in the [local lifecycle guide](docs/runbook/local-lifecycle.md).
Only local Development and local Test exist today. Local checks are not
Production readiness.

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
