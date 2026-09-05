# Scale separate Research, Batch, and Tracking pools with single-slot Workers

Ordinary Research, Batch Research, and Tracking use independently scaled single-slot Worker roles sharing one calculation kernel. Supervisors own claims, fences, data protection, and publication while children calculate only, trading some capacity flexibility for isolated workloads and one verifiable publication authority.
