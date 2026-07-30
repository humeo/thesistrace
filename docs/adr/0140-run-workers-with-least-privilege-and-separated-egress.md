---
status: accepted
---

# Run Workers with least privilege and separated egress

Hosted Platform V2 runs shared Compute Workers as least-privilege non-root processes with separated service identities, read-only roots, and no Docker socket, privileged mode, arbitrary host mount, or general Internet and Tushare egress. Their only writable mounts are bounded private scratch and the controlled shared `WorkingCacheStore` named volume, while immutable objects remain accessible only through the private `ObjectStore` boundary. The Data Worker alone receives the additional Tushare egress required for Dataset Publication.
