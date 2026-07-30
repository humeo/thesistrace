# ThesisTrace

ThesisTrace is a single-node workspace for reproducible, post-close A-share
factor research, strategy backtesting, and daily tracking.

The implementation is being built ticket-by-ticket from
`.scratch/thesistrace-v1-research-platform/`.

## Local development

Install the backend and frontend dependencies once:

```sh
uv sync
bun install --cwd web
```

Then start the API, persistent worker, and Web UI together:

```sh
make dev
```

Open `http://127.0.0.1:5173`. Local metadata and immutable objects are stored
under `.local/` and survive process restarts.

Run the current backend, frontend, and browser acceptance checks with:

```sh
make check
```
