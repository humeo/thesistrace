# 19 — Operate three bounded Health views

**What to build:** Give the Operator distinct, privacy-safe System Health, Data
Health, and Quantitative Semantic Health views with bounded telemetry so one
plane's failure is visible without falsely declaring unrelated capabilities
dead.

**Blocked by:** 08 — Recover, cancel, and fence Research Workflows; 10 — Publish Datasets on the independent Data Worker; 12 — Advance DailyTrack through finite Workflows; 14 — Lock down the five-Worker topology.

**Status:** ready-for-agent

- [ ] Every long-running service exposes cheap dependency-independent liveness and role-specific readiness without performing storage writes or expensive calculations.
- [ ] System Health covers public dependencies, outbox lag, Task Queues, Worker heartbeats, Workflow capacity, and disk pressure without treating a Tushare or telemetry failure as total service death.
- [ ] Data Health covers Tushare reachability, Dataset Publication freshness, validation, coverage, schema, lineage, and failed publication while preserving the previous Release.
- [ ] Quantitative Semantic Health covers deterministic regression, numeric and accounting invariants, checksums, missingness, and explicit equivalence evidence without presenting Alpha profitability as health.
- [ ] OpenTelemetry instrumentation, one Collector, Prometheus, and Grafana produce three separate low-cardinality dashboard views and non-blocking external trace export.
- [ ] Metrics, logs, traces, and Temporal payloads exclude credentials, emails, research expressions, market payloads, result payloads, and Personal Workspace identifiers with unbounded cardinality.
- [ ] Prometheus, rotated JSON logs, and trace sampling obey the specified size, time, and failed-versus-successful retention bounds, and dropped-export failure is itself visible.
- [ ] Fault injection in each plane changes only the appropriate dashboard and readiness behavior; no alert-delivery service is introduced, and the daily Operator inspection practice is documented.
