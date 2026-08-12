---
status: accepted
---

# Use one full Compose topology for local Development and Test

The active local lifecycle uses one base Compose topology. The topology owns
Web, API, Worker, PostgreSQL, RustFS, and one-shot schema initialization.
Persistent local Development and disposable local Test select different
overlays, project identities, ports, and data lifecycles without selecting
different product runtimes.

This replaces the former hybrid arrangement in which infrastructure ran in
Compose while Web, API, and Worker ran as unrelated host processes. One service
graph makes schema initialization ordering, readiness, networking, state
ownership, and failure diagnostics observable at the same boundary in both
environments.

Fast checks and the integration and browser host test runners remain on the
host under mise, pnpm, and uv. Integration runners address only their newly
created PostgreSQL and RustFS project; Playwright addresses only the Web origin
of its newly created full topology. This keeps feedback direct without creating
a second application topology.

## Consequences

- Development preserves named volumes across stop/start and deletes them only
  through an identity-checked reset.
- Every Test run receives a unique project, random host ports, isolated volumes
  and bucket, evidence-before-cleanup behavior, and deterministic teardown.
- Compose Watch owns source synchronization and service-appropriate reload,
  restart, or rebuild behavior.
- Container dependency directories remain separate from host dependency
  directories.
- Image builds and the complete gate cost more than the former hybrid startup;
  consistent runtime boundaries and reproducible evidence are worth that cost.
- The decision defines only local Development and Test.
  Its evidence is not Production readiness and creates no remote environment
  contract.
