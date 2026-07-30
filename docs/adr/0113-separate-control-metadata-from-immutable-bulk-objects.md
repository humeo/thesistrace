---
status: accepted
---

# Separate control metadata from immutable bulk objects

Hosted Platform V2 stores identity, Personal Workspace ownership, Research
Definition and lifecycle state, scheduling, quota, idempotency, Dataset Release
manifests, and object indexes in InsForge PostgreSQL. Canonical Market Data,
Alpha Matrices, Result Bundles, Tracking Checkpoints, and other large immutable
payloads remain content-addressed objects outside PostgreSQL.

Large tabular objects use partitioned columnar encoding, initially Parquet, so
the Compute Plane can read only the required dates, fields, and instruments
rather than materializing a complete Release as JSON. Object access goes
through a location-independent `ObjectStore` port. Application contracts use
opaque object keys and never expose host filesystem paths.

The first Compose deployment implements that port with an InsForge Storage
adapter. InsForge Storage stores bytes in its local `STORAGE_DIR` Docker
persistent volume on the node's SSD. Hosted Platform V2 does not deploy MinIO,
RustFS, or another S3-compatible service at launch. InsForge PostgreSQL remains
authoritative for domain manifests, ownership, quota accounting, checksums,
references, and deletion state; the Storage backend is not treated as the
source of those domain facts.

The launch adapter uses private InsForge Storage APIs rather than exposing
storage credentials or paths to Users. Object immutability, write admission,
and per-workspace quota remain application rules. Parquet partitions and the
configured Storage upload limit must keep individual objects within the
verified single-node workload envelope.

If multiple application nodes need shared object access, multipart or
S3-compatible access becomes necessary, or measured Storage throughput becomes
a bottleneck, InsForge Storage may be moved to an external S3-compatible
backend. That change must include an explicit migration and verification of
existing objects; switching the backend does not imply that local objects move
automatically. The `ObjectStore` port and domain manifests remain unchanged.
