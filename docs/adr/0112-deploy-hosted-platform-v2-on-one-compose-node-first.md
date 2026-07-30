---
status: accepted
---

# Deploy Hosted Platform V2 on one Compose node first

Hosted Platform V2 initially deploys on one 6-core, 12-GB node with a 200-GB
persistent SSD and Docker Compose. Its Control Plane, Scheduling Plane, Data
Plane, and Compute Plane remain logically isolated responsibilities but do not
require multi-node infrastructure. Separate processes or containers may enforce
runtime and resource boundaries without turning the four planes into four
distributed service clusters.

The logical boundaries are:

- the Control Plane contains the Web/API, InsForge Auth integration, Personal
  Workspace ownership, Research Definition lifecycle, quotas, task product
  state, and the execution outbox;
- the Scheduling Plane is Temporal durable orchestration and fair Task Queue
  dispatch, without a parallel ThesisTrace Scheduler;
- the Data Plane contains Tushare ingestion, normalization, the one-slot Data
  Worker, and platform-owned shared immutable Dataset Releases; and
- the Compute Plane contains CPU Activity Workers for Alpha calculation, Alpha
  Matrix production, Factor Evaluation, Strategy Backtest, Daily Tracking,
  equivalence verification, and maintenance-only Tracking Generation rebuilds.

PostgreSQL and object storage are shared persistence boundaries rather than a
fifth execution plane. Shared Dataset objects and Workspace-owned computed
artifacts retain their different ownership even when they use the same object
storage service. OpenTelemetry, Prometheus, Grafana, and structured logs observe
all four planes rather than belonging to only one of them.

The first hosted release adds no independent Project hierarchy, organization
RBAC, billing or payments, GPU Worker pool, parameter-sweep product, or generic
portfolio optimizer. Quotas and capacity measurements do not imply billing.

The node is the current deployment capacity boundary, not a permanent
architecture constraint. This topology provides no high availability: failure
of the node interrupts the hosted platform.
