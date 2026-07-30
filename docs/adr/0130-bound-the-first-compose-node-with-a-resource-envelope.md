---
status: accepted
---

# Bound the first Compose node with a resource envelope

The first Hosted Platform V2 deployment treats its 6 CPU cores and 12 GiB of
memory as a hard capacity boundary. Docker resource limits reserve enough host
capacity for Linux, Docker, the kernel, filesystem cache, and operator recovery
instead of allowing application containers to consume the entire node.

Each of the four Compute Worker containers has a 1 GiB memory hard limit and a
0.75 CPU cap. The one Data Worker has a 1 GiB memory hard limit and a 0.5 CPU
cap. Caddy and its hosted Web assets, API processes, InsForge services,
PostgreSQL, Temporal, OpenTelemetry Collector, Prometheus, Grafana, and other
non-worker containers together receive no more than 5 GiB of memory hard limits
and 2 CPU cores. At least 2 GiB of memory and 0.5 CPU remain outside those
container budgets for the host.

Before Compute concurrency four is enabled for invited Users, representative
maximum workloads must demonstrate, for every Compute Worker:

- memory-use p99 at or below 700 MiB;
- an absolute peak at or below 800 MiB;
- no out-of-memory event, swap activity, or unexpected container restart; and
- correct completion under its CPU throttling and Activity heartbeat limits.

These values are launch protection settings, not permanent workload capacity or
research-domain limits. A workload that cannot fit this envelope must be
optimized or rejected before execution; the first response is not to remove
the host reserve or let one Worker borrow the Control Plane's memory. Any
change to the worker limits or concurrency requires a new representative
capacity result.
