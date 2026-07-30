---
status: accepted
---

# Separate liveness, readiness, and System Health

Every long-running Hosted Platform V2 service exposes or supplies a lightweight
Service Liveness signal and a role-specific Service Readiness signal. Liveness
checks only whether the process can make internal progress. Readiness checks
the required PostgreSQL, Temporal, InsForge Storage, or upstream service
connections needed for that service to accept its own traffic or Activities.
System Health aggregates those service signals with Task Queue, heartbeat,
capacity, Data Health, and Quantitative Semantic Health evidence for operators.

Steady Caddy, InsForge, PostgreSQL, Temporal, API, Worker, OpenTelemetry
Collector, Prometheus, and Grafana containers use `restart: unless-stopped` for
process crashes and node restarts. One-shot migration, backup, restore, and
verification jobs do not enter an automatic restart loop.

A failed readiness check removes or blocks new work and raises an operator
signal; repeatedly restarting a healthy process does not repair an unavailable
dependency. Tushare failure degrades Dataset Publication and Data Health but
does not make the whole product API unready. An external trace exporter,
OpenTelemetry Collector, Prometheus, or Grafana failure degrades observability
but does not block accepted research or data work.

Health probes must remain cheap and bounded. They do not create and delete an
object on each request, run quantitative regressions, contact Tushare, or query
high-cardinality task histories. Storage readiness uses a read-only capability
check or a separately scheduled canary rather than turning every probe into a
write workload.
