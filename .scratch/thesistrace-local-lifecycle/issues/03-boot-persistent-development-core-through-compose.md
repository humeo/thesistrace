# 03 — Boot the persistent Development Core through Compose

**What to build:** Let a developer bootstrap, start, reach, and stop the full
ThesisTrace Core through one Compose topology while preserving Development data
across ordinary stops.

**Blocked by:** 02 — Extract the one-shot database migration boundary.

**Status:** ready-for-agent

- [ ] `pnpm bootstrap` installs the required host dependencies, validates
      configuration, and prepares the local Development service images.
- [ ] `pnpm dev:up` starts Web, API, Worker, PostgreSQL, RustFS, and the one-shot
      Migration service in the canonical Development project.
- [ ] The command waits until every required long-running service is healthy
      and fails when migration or readiness fails.
- [ ] A browser can open the four-resource Web product and the public HTTP
      interface can perform a Core request through the Compose topology.
- [ ] The Worker can claim and complete real Core work against the same
      PostgreSQL and RustFS services.
- [ ] `pnpm dev:stop` stops the Development project without deleting its data
      volumes.
- [ ] Restarting after stop preserves previously created product resources and
      immutable publication objects.
- [ ] A first start against empty Development data performs migration but does
      not automatically publish Fixture data or create product resources.
- [ ] Development and Test use explicit non-secret configuration, and pinned
      infrastructure images contain no floating latest tags.
- [ ] Host and container dependency directories remain independent.
