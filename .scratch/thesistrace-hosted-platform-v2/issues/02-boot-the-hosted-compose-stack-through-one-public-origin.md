# 02 — Boot the Hosted Compose stack through one public Origin

**What to build:** Start a version-pinned, production-like single-node Hosted
Platform stack whose static Web application and API are reachable through one
Caddy Origin while every data, execution, observability, and administration
service remains private.

**Blocked by:** 01 — Expand Hosted runtime ports without breaking V1.

**Status:** ready-for-agent

- [ ] One documented command starts the production Web build, Caddy, API, InsForge Auth and Storage, PostgreSQL, Temporal, Data Worker, four Compute Workers, OpenTelemetry Collector, Prometheus, and Grafana with pinned component versions.
- [ ] Caddy is the only application container binding host ports 80 and 443, serves built Web assets directly, and no long-running Vite development server exists in the production stack.
- [ ] PostgreSQL, Storage, Temporal, Workers, metrics, dashboards, and administration endpoints are reachable only on private service networks.
- [ ] Version-pinned one-shot bootstrap migrations finish successfully before steady services start, and an injected migration failure prevents the public application from becoming ready.
- [ ] A black-box smoke test reaches Web and cheap API health only through the public Origin or its acceptance-equivalent trusted edge.
- [ ] A clean stop and restart preserves the stack's PostgreSQL, Temporal, and immutable-object volumes.
