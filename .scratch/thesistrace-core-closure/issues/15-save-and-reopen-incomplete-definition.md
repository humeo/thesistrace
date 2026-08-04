# 15 — Save and reopen an incomplete Research Definition

**What to build:** Let a user create, save, list, and reopen an incomplete
Research Definition through real PostgreSQL without a Draft or frozen-version
product resource.

**Blocked by:** 03.

**Status:** ready-for-agent

**Implementation:** complete

- [x] First Save may omit name, hypothesis, Alpha, or other runnable values.
- [x] An omitted name is generated once, remains stable after reopen, and may
  later be edited; hypothesis always remains optional.
- [x] Creating a Definition requires no expected revision, and every successful
  Save advances revision exactly once.
- [x] The Definitions module owns its schema, migrations, SQL, and product
  projection.
- [x] Definition list and stable detail URL survive HTTP and worker restart.
- [x] The API and Web expose no Draft, Snapshot, frozen version, database row,
  or internal lifecycle resource.
- [x] The page has observable loading, save, refresh, empty, and error states.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_definition_save.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must save and reopen a nameless incomplete Definition through
real PostgreSQL across independent HTTP and worker process restarts. The browser
test must reopen its stable detail URL with the same generated name and revision.

## Comments

- The canonical `definition` module owns its PostgreSQL schema, migration,
  records SQL, revision update, and public list/detail projections. Core HTTP
  exposes create, list, detail, and Save without reusing the legacy SQLite
  Definition lifecycle.
- First Save accepts `{}` and writes revision `1`. It generates and persists a
  stable name, while hypothesis, Alpha, Universe, neutralization, holdings
  count, and rebalance interval remain optional. An update requires the current
  expected revision, may edit the generated name, and advances once.
- The backend ticket command passed `14 passed, 1 warning`, including a real
  PostgreSQL Save/reopen and a real `thesistrace-core-worker --once` process
  between independent HTTP lifetimes.
- The canonical Web supports `/definitions` and stable
  `/definitions/def_*` detail URLs. The final browser command passed `2 passed`
  in `23.7s`, covering empty/new/save/reopen/list/detail Refresh, generated-name
  stability, a failed network Refresh with Retry, and clearing an optional
  hypothesis through revision `3`.
- Review found and closed editor state-machine defects: create initially
  refreshed the list instead of the saved detail; Save/Refresh/Retry lacked
  error and duplicate-operation guards; empty hypothesis was omitted instead
  of cleared; the new package was absent from architecture scans; StrictMode
  loads could race; failed Refresh retained stale success status; and a
  suppression branch omitted unmount cleanup. The final implementation fences
  loads with AbortController plus generation checks, guards all operations,
  preserves the current editor, and invalidates requests before abort on
  unmount. Final independent review passed `Standards: PASS` and `Spec: PASS`.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `518 passed, 51 skipped, 2 warnings`, Web typecheck/build passed, and
  narrow/desktop Playwright passed in `35.5s` and `31.9s`.
