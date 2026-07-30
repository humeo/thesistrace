---
status: accepted
---

# Operate three health dashboards

The first hosted release provides operators with three distinct Grafana
dashboard views. They are separate views of one observability stack, not three
monitoring systems.

The System Health dashboard covers:

- API and Auth availability, error rate, and latency;
- PostgreSQL and object-storage dependency health;
- queued work count and oldest wait age by P1/P3 priority, active Compute slots,
  Temporal Worker and Activity heartbeat or timeout state, Attempt outcomes,
  and Dataset Publication executor state;
- disk-pressure levels, CPU, memory, container restarts, and process health; and
- OpenTelemetry Collector export backlog and dropped telemetry.

The Data Health dashboard covers:

- expected versus latest published market session and publication delay;
- Dataset Publication outcomes and duration;
- Tushare request, throttling, and source failure outcomes; and
- coverage, unexplained missingness, duplicates, schema failures, and hard-gate
  failures by low-cardinality Dataset Family and check identity.

The Quantitative Semantic Health dashboard covers:

- ResearchRun and Tracking Advance outcomes and duration;
- Alpha invalid-value and coverage behavior;
- numeric, accounting, checksum, and other semantic invariant failures; and
- historical-correction boundaries and explicit release-sequence
  Batch-Incremental Equivalence verification outcomes.

Statistical Alpha, Factor, or Strategy movement remains warning evidence rather
than a correctness failure. Prometheus labels remain low-cardinality and never
contain User, Workspace, task, Attempt, trace, Alpha Expression, or research
result identifiers. Attempt-specific diagnosis uses authorized product state,
structured logs, and traces within their operational retention instead of
per-artifact validation reports.
