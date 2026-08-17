---
status: accepted
---

# Configure Worker capacity and use 2c2g in development

Research Worker Capacity and Tracking Worker Capacity are independent
deployment-level CPU and hard-memory declarations consumed by their
authoritative planners and every homogeneous replica in that pool. Each limit
is enforced across the complete Worker container, including its supervisor and
one execution child. Worker startup fails when its actual cgroup limits are
below its role declaration instead of silently running with less capacity.

The development and test profile is 2 vCPU and 2 GiB per single-slot Worker.
Arrow and NumPy may use at most two execution threads, and Research Chunk or
Tracking Advance planning may consume at most 75 percent, or 1.5 GiB, of the
memory limit. The remaining 512 MiB is reserved for Python, PyArrow,
object-store and PostgreSQL clients, serialization, and bounded runtime
variation.

Deployments may change either pool's declaration and matching container limits
without changing calculation semantics or creating another engine. Research
admission freezes its Chunk plan; Tracking Advance creation freezes its Target
and capacity facts. Increasing capacity remains compatible with existing plans.
Decreasing capacity requires draining or stopping non-terminal work whose
frozen peak plan exceeds the new slot before rollout. A Worker never silently
replans accepted work.

This specializes ADR-0201's Research Execution Slot and ADR-0208's fixed-role
Tracking Worker while preserving one active Attempt per Worker and horizontal
scaling by replica count. CPU, memory, and thread limits are not exposed as
user or per-work-item configuration.
