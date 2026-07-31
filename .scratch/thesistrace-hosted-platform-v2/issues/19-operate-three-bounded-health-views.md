# 19 — Operate three bounded Health views

**What to build:** Give the Operator distinct, privacy-safe System Health, Data
Health, and Quantitative Semantic Health views with bounded telemetry so one
plane's failure is visible without falsely declaring unrelated capabilities
dead.

**Blocked by:** 08 — Recover, cancel, and fence Research Workflows; 10 — Publish Datasets on the independent Data Worker; 12 — Advance DailyTrack through finite Workflows; 14 — Lock down the five-Worker topology.

**Status:** resolved

- [x] Every long-running service exposes cheap dependency-independent liveness and role-specific readiness without performing storage writes or expensive calculations.
- [x] System Health covers public dependencies, outbox lag, Task Queues, Worker heartbeats, Workflow capacity, and disk pressure without treating a Tushare or telemetry failure as total service death.
- [x] Data Health covers Tushare reachability, Dataset Publication freshness, validation, coverage, schema, lineage, and failed publication while preserving the previous Release.
- [x] Quantitative Semantic Health covers deterministic regression, numeric and accounting invariants, checksums, missingness, and explicit equivalence evidence without presenting Alpha profitability as health.
- [x] OpenTelemetry instrumentation, one Collector, Prometheus, and Grafana produce three separate low-cardinality dashboard views and non-blocking external trace export.
- [x] Metrics, logs, traces, and Temporal payloads exclude credentials, emails, research expressions, market payloads, result payloads, and Personal Workspace identifiers with unbounded cardinality.
- [x] Prometheus, rotated JSON logs, and trace sampling obey the specified size, time, and failed-versus-successful retention bounds, and dropped-export failure is itself visible.
- [x] Fault injection in each plane changes only the appropriate dashboard and readiness behavior; no alert-delivery service is introduced, and the daily Operator inspection practice is documented.

## Comments

- Added cheap role probes, three bounded health projections, persisted bounded
  PostgreSQL evidence, live Temporal Task Queue/poller evidence, deterministic
  semantic regression, sanitized structured telemetry, bounded retention, and
  three provisioned Grafana dashboards with loopback-only Operator access.
- Unit and integration verification: `256 passed, 15 skipped`; `ruff check .`,
  Compose quiet validation, pinned Collector validation, and pinned
  `promtool check config` all passed.
- Live Compose acceptance proved all steady containers healthy, the public
  Origin smoke, five live Temporal queue snapshots, four Worker slots, eleven
  Prometheus targets, all three provisioned Grafana dashboards, denied private
  product-table access for the health role, and System/Data/Quantitative fault
  injection with unchanged readiness. The external trace backend is
  intentionally absent locally, so only `trace_export` remains degraded in the
  normal System view.
