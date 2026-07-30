---
status: accepted
---

# Run Workers with least privilege and separated egress

Hosted Platform V2 runs ThesisTrace Compute Workers as non-root processes with
a read-only root filesystem, `no-new-privileges`, and no unnecessary Linux
capabilities. They receive no Docker socket, privileged mode, host process or
network namespace, arbitrary host-directory mount, or direct mount of the
physical InsForge Storage volume. Each Worker has only its bounded writable
scratch location and accesses immutable objects through the private
`ObjectStore` adapter and InsForge Storage API.

Compute Workers run on an internal network that permits only the PostgreSQL,
Temporal, InsForge Storage, and OpenTelemetry Collector connections required by
their Activities. They have no general Internet or Tushare access and perform
no runtime package download. The Data Worker uses a separate network path that
allows Tushare egress in addition to its required private platform services.

Database roles, Storage credentials, and Temporal identities are separated by
service role. Workers do not receive end-User credentials or impersonate a
User, and one role's secret does not grant every platform capability.

The four Compute containers remain a shared pool across Personal Workspaces;
this decision does not create one operating-system container per User. That
shared model relies on the frozen Alpha Expression contract rejecting arbitrary
Python, SQL, shell commands, plugins, and user-defined executable code.
