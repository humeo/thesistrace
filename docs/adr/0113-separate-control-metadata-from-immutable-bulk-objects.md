---
status: accepted
---

# Separate control metadata from immutable bulk objects

Hosted Platform V2 keeps product truth and control metadata in InsForge PostgreSQL, while immutable bulk payloads use content-addressed objects through a private, location-independent `ObjectStore` port backed initially by InsForge Storage; growing tabular data uses partitioned Parquet. This separation preserves PostgreSQL authority for ownership, manifests, quota, and lifecycle while enabling selective reads and later storage-backend migration without exposing physical paths.
