---
status: accepted
---

# Self-host one Temporal Service with PostgreSQL Visibility

The first Hosted Platform V2 deployment self-hosts Temporal on the same
single-node Docker Compose installation as ThesisTrace and InsForge. One
`temporalio/server` container runs the Temporal server roles together. This is
an explicit limited-capacity, non-HA topology rather than a claim of a
production Temporal cluster.

Temporal shares the PostgreSQL server process already present on the node but
does not share application databases, schemas, roles, or connection
credentials. It uses dedicated `temporal` persistence and
`temporal_visibility` databases with dedicated roles. PostgreSQL provides
Visibility; the first deployment adds no Elasticsearch or OpenSearch service.

A version-pinned, one-shot schema initialization or migration task runs the
matching Temporal schema tools before a server upgrade becomes active. The
deployment uses neither the Temporal development server nor an auto-setup image
as its steady-state server. ADR-0134 coordinates this task with the other
release migrations.

Temporal gRPC, administration endpoints, and any optional Temporal UI remain on
private Compose or operator-only networks and are never exposed as public
tenant endpoints. Temporal Service and SDK metrics join the existing
Prometheus and Grafana stack.

The Temporal container and its PostgreSQL connections receive bounded resource
configuration. Representative end-to-end capacity tests must revalidate the
initial Compute concurrency of four after Temporal, InsForge, PostgreSQL, and
observability are running together. Failure of this node still interrupts the
entire platform; Temporal improves durable process recovery but does not add
host availability.
