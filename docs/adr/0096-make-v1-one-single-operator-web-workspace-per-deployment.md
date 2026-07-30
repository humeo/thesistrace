---
status: accepted
---

# Make V1 one single-operator Web Workspace per deployment

One ThesisTrace V1 deployment provides one Web Workspace for one operator. The
Workspace may contain many Research Definitions, ResearchRuns, Dataset
Releases, and reports, but V1 does not introduce User, Organization, Tenant,
membership, sharing, or RBAC domain models.

The application is deployed as a single-node Web product. If access control is
needed, the deployment boundary is responsible for it rather than application
records pretending to support multiple owners.

A future hosted multi-user product may add an explicit ownership and tenancy
model. V1 does not pre-build that model or make existing research semantics
depend on it.
