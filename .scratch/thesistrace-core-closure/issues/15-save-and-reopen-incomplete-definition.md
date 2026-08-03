# 15 — Save and reopen an incomplete Research Definition

**What to build:** Let a user create, save, list, and reopen an incomplete
Research Definition through real PostgreSQL without a Draft or frozen-version
product resource.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] First Save may omit name, hypothesis, Alpha, or other runnable values.
- [ ] An omitted name is generated once, remains stable after reopen, and may
  later be edited; hypothesis always remains optional.
- [ ] Creating a Definition requires no expected revision, and every successful
  Save advances revision exactly once.
- [ ] The Definitions module owns its schema, migrations, SQL, and product
  projection.
- [ ] Definition list and stable detail URL survive HTTP and worker restart.
- [ ] The API and Web expose no Draft, Snapshot, frozen version, database row,
  or internal lifecycle resource.
- [ ] The page has observable loading, save, refresh, empty, and error states.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` against real
  PostgreSQL, including a nameless and incomplete Save followed by restart.
- Run `bun run --cwd web test:e2e` and confirm the saved Definition reopens at
  the same URL with the same generated name and revision.

## Comments
