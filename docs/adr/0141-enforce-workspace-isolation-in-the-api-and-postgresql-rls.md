---
status: accepted
---

# Enforce Workspace isolation in the API and PostgreSQL RLS

Browsers use the public InsForge Auth routes for identity and sessions, but do
not directly query ThesisTrace product tables through PostgREST. Every product
operation goes through the ThesisTrace API, which verifies the InsForge JWT and
maps its User identity to the one authoritative Personal Workspace. A request
cannot select or override its Workspace through a body, query parameter,
header, or object key.

Every Workspace-owned product table has a non-null `workspace_id` and
PostgreSQL row-level security policies. The API database role is neither a
superuser nor a `BYPASSRLS` role. Each transaction sets its Workspace context
only from the verified server-side identity mapping, so API authorization and
database RLS independently constrain the same operation.

Compute Workers, the Data Worker, and the execution-outbox relay use separate
service roles rather than end-User JWTs. Their grants are limited to their
platform responsibilities. Platform-owned Dataset Releases are readable to
authenticated product operations but writable only through the Data Worker
publication path.

An object path or Workspace-shaped prefix is an organization convention, not
an authorization boundary. Download, deletion, and signed-access decisions use
the authoritative PostgreSQL ownership and manifest records before InsForge
Storage serves bytes.

Hosted-release acceptance includes negative cross-Workspace tests for listing,
reading, updating, cancelling, deleting, and downloading every private resource
class. A failure in either the API authorization layer or an RLS policy may not
turn those tests into successful access.
