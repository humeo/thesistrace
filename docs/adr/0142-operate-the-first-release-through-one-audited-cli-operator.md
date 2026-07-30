---
status: accepted
---

# Operate the first release through one audited CLI Operator

The first Hosted Platform V2 deployment has one trusted Operator. Operator
actions use SSH and versioned administrative CLI or release commands; the
product exposes no public Admin UI, multi-Operator membership model, or
Operator RBAC in the first release.

The Operator may issue and revoke Registration Invitations, apply explicit
Quota Profile overrides, execute maintenance and release procedures, manage
secrets and backups, perform disaster recovery, inspect private operational
dashboards, and invoke authorized manual Dataset Publication. This authority
does not transfer ownership of a User's Personal Workspace or make private
research resources part of an Operator workspace.

Every state-changing administrative command writes an append-only management
audit event to InsForge PostgreSQL. The event records a stable Operator
identity, action, target identity, time, outcome, and request or release
correlation without copying credentials, Alpha Expressions, market-data
payloads, or result payloads. Product APIs cannot update or delete these audit
events.

Structured container logs may help diagnose a management action, but they are
rotated operational evidence rather than the authoritative management audit
record. Introducing more Operators or a public administration surface requires
a later authorization and audit decision.
