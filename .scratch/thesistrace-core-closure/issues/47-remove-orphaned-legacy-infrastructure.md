# 47 — Remove orphaned legacy infrastructure

**What to build:** Contract the remaining shared legacy infrastructure and the
temporary expression adapter only after every active caller has migrated.

**Blocked by:** 46.

**Status:** ready-for-agent

- [ ] SQLite Product State and its runtime assembly are removed.
- [ ] Global metadata ports, repository-per-table interfaces, generic command
  envelopes, no-op dispatch seams, and old lifecycle facades are removed.
- [ ] The temporary string-expression compatibility boundary is removed after
  every active caller uses the normalized tree.
- [ ] Orphaned old HTTP, storage, tracking, worker, configuration, dependencies,
  scripts, and tests are deleted rather than wrapped.
- [ ] One PostgreSQL and standard-S3 Core implementation remains; there is no
  runtime-mode selector or hidden fallback.
- [ ] Current documentation and default targets describe only the active Core,
  while ADR and archived history remain preserved.

**How to verify:**

- Run `uv run pytest -q tests/kernel tests/architecture tests/adapters tests/integration tests/acceptance`
  and the Web typecheck/build after removing orphaned infrastructure.
- Inspect the dependency graph, executable entrypoints, configuration, and
  repository search results; none may reference a second runtime or temporary
  expression adapter.

## Comments
