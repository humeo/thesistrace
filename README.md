# ThesisTrace

ThesisTrace is a single-node workspace for reproducible, post-close A-share
factor research, strategy backtesting, and daily tracking.

The active implementation is the module-first Core described in
[`docs/architecture/core.md`](docs/architecture/core.md).

## Local development

Install the backend and frontend dependencies once:

```sh
uv sync
bun install --cwd web
```

Docker must be available for the development PostgreSQL and S3-compatible
object store. Start those dependencies, the API, worker, and Web UI together:

```sh
make dev
```

Open `http://127.0.0.1:5173`. Development uses the same PostgreSQL and standard
S3 interfaces as every future deployment; there is no local product runtime or
SQLite fallback. Use `make dev-reset` to clear the development data or
`make dev-down` to stop and remove it.

The current Tushare adapter has a separate
[credential verification guide](docs/runbook/tushare-live-bootstrap.md).

Run the current backend, frontend, and browser acceptance checks with:

```sh
make check
```
