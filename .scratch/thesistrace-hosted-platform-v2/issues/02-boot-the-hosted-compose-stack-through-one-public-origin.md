# 02 — Boot the Hosted Compose stack through one public Origin

**What to build:** Start a version-pinned, production-like single-node Hosted
Platform stack whose static Web application and API are reachable through one
Caddy Origin while every data, execution, observability, and administration
service remains private.

**Blocked by:** 01 — Expand Hosted runtime ports without breaking V1.

**Status:** resolved

- [x] One documented command starts the production Web build, Caddy, API, InsForge Auth and Storage, PostgreSQL, Temporal, Data Worker, four Compute Workers, OpenTelemetry Collector, Prometheus, and Grafana with pinned component versions.
- [x] Caddy is the only application container binding host ports 80 and 443, serves built Web assets directly, and no long-running Vite development server exists in the production stack.
- [x] PostgreSQL, Storage, Temporal, Workers, metrics, dashboards, and administration endpoints are reachable only on private service networks.
- [x] Version-pinned one-shot bootstrap migrations finish successfully before steady services start, and an injected migration failure prevents the public application from becoming ready.
- [x] A black-box smoke test reaches Web and cheap API health only through the public Origin or its acceptance-equivalent trusted edge.
- [x] A clean stop and restart preserves the stack's PostgreSQL, Temporal, and immutable-object volumes.

## Comments

- `make hosted-up` is implemented by `scripts/hosted-stack`; component versions,
  InsForge source, and the Deno runtime image are pinned.
- `hosted public-Origin smoke passed` was observed before and after a full
  `down`/`up` cycle.
- The restart preserved the ThesisTrace migration checksum, Temporal's
  `temporal` and `temporal_visibility` databases, and a marker in the
  `immutable-objects` volume.
- With `THESISTRACE_INJECT_MIGRATION_FAILURE=1`, migrations exited 1 while
  `release-gate`, `api`, and `edge` remained unstarted.
