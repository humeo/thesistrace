---
status: accepted
---

# Run version-pinned migrations before steady services

Hosted Platform V2 applies schema and platform bootstrap changes through
explicit, version-pinned, one-shot Compose jobs. The ThesisTrace API, Workers,
and Temporal Server do not perform hidden schema migration as a side effect of
normal process startup.

For a new release, the operator first verifies the required encrypted off-node
backup. After PostgreSQL is healthy, the release runs the matching InsForge,
ThesisTrace product-schema, and Temporal persistence and Visibility migration
jobs. Steady InsForge, Temporal, and ThesisTrace API services start only after
all required jobs exit successfully. Data and Compute Workers start after their
dependencies are ready, and Caddy exposes the release only after the
end-user-facing services pass readiness.

Failure of any migration prevents the new steady services and Workers from
starting. It is an operator-visible release failure, not a partially available
product state. Migration logs follow the structured production logging rules
and must not print credentials or database contents.

The first single-node deployment uses an announced maintenance window for
schema-changing releases. It does not claim rolling migration, mixed-version
compatibility, or zero-downtime upgrades.
