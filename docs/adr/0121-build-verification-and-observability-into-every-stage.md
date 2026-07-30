---
status: accepted
---

# Build verification and observability into every stage

Testing, regression protection, and observability are synchronous parts of
each Hosted Platform V2 delivery stage. They are not a final hardening phase.
A stage is incomplete until its new behavior has proportionate automated
checks, regression evidence, runtime signals, and an operator response path.

The platform observes three independent kinds of health:

- System Health asks whether services can safely accept, schedule, execute,
  persist, and serve work.
- Data Health asks whether Tushare inputs and published Dataset Releases are
  timely, complete, schema-valid, internally consistent, and attributable.
- Quantitative Semantic Health asks whether Alpha, Factor, Strategy, and Daily
  Tracking outputs continue to honor their frozen numeric, domain, and
  reproducibility contracts.

The same distinction applies before and after deployment. Tests exercise
contracts and failure cases, regression suites compare behavior against
controlled evidence, and runtime checks observe real executions and published
artifacts. A healthy process, container, or host does not establish Data Health
or Quantitative Semantic Health. CPU and memory monitoring are necessary
System Health signals but are not the platform's observability model.

The exact checks, blocking rules, warning thresholds, retention, and telemetry
components remain separate decisions.
