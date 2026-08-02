# 35 — Prove the Bounded Local Operational Health Profile

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Start observability only while heavy product work is idle and
prove the three production Health views against the retained local witness. Show
that the profile is operable within the development envelope without presenting
it as co-resident production capacity evidence.

**Blocked by:** 29 — Prove Local Identity, Isolation, and Retained Product Health.

**Status:** ready-for-agent

- [ ] The gate confirms no Compute or Data Activity is running, then starts Collector, Prometheus, and Grafana under explicit local CPU and memory bounds while Compute Workers 2–4 remain disabled.
- [ ] Named readiness checks prove Collector ingestion, Prometheus query, Grafana datasource access, and the required API/worker heartbeats without treating container process state as application health.
- [ ] System Health, Data Health, and Quantitative Semantic Health render or return the retained product witness with correct freshness, availability, degradation, and failure semantics; Data and Quantitative views remain independently diagnosable.
- [ ] System Health reports the exact local backup, restore, workflow, queue, and heartbeat gaps rather than inferring healthy production recovery from a running Compose stack.
- [ ] Bounded time-series and log queries work for the required window, and telemetry redaction tests prove no token, credential, raw prompt, private research payload, or unbounded user-controlled label is exported.
- [ ] Peak and time-series CPU, memory, swap, disk, container restart, and heartbeat observations are recorded for this operational phase, including the configured limits rather than only instantaneous usage.
- [ ] Observability resources are stopped after success before another heavy gate starts; failure preserves diagnostics under the selected cleanup policy. Evidence explicitly makes no production capacity, retention, alert-routing, or launch claim.
