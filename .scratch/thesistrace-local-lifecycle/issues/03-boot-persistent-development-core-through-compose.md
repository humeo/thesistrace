# 03 — Boot the persistent Development Core through Compose

**What to build:** Let a developer bootstrap, start, reach, and stop the full
ThesisTrace Core through one Compose topology while preserving Development data
across ordinary stops.

**Blocked by:** 02 — Extract the one-shot database migration boundary.

**Status:** complete

- [x] `pnpm bootstrap` installs the required host dependencies, validates
      configuration, and prepares the local Development service images.
- [x] `pnpm dev:up` starts Web, API, Worker, PostgreSQL, RustFS, and the one-shot
      Migration service in the canonical Development project.
- [x] The command waits until every required long-running service is healthy
      and fails when migration or readiness fails.
- [x] A browser can open the four-resource Web product and the public HTTP
      interface can perform a Core request through the Compose topology.
- [x] The Worker can claim and complete real Core work against the same
      PostgreSQL and RustFS services.
- [x] `pnpm dev:stop` stops the Development project without deleting its data
      volumes.
- [x] Restarting after stop preserves previously created product resources and
      immutable publication objects.
- [x] A first start against empty Development data performs migration but does
      not automatically publish Fixture data or create product resources.
- [x] Development and Test use explicit non-secret configuration, and pinned
      infrastructure images contain no floating latest tags.
- [x] Host and container dependency directories remain independent.

## Comments

- Implemented in `d605e59`; review fixes landed in `67e7a5d`.
- Verified real `pnpm bootstrap`, all six Compose service boundaries, one-shot
  migration, health-gated startup, and an empty first-start product.
- In-app browser acceptance covered Data, Definitions, Research Runs, and Daily
  Tracks. A Web Data Update was completed by the Compose Worker and produced
  `dsr_cd03ff1ef76beb7749dac512`; `dev:stop`/`dev:up` preserved that release.
- Two review rounds used the fixed point `df83ca2`; final Standards and Spec
  reviews reported no findings.
