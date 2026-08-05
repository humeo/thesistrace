---
status: superseded by ADR-0151
scope: archived - outside the active Core
---

# Operate the first release through one audited CLI Operator

The first Hosted Platform V2 release has one trusted Operator who acts through versioned CLI and release commands over SSH, with no public Admin UI, multi-Operator model, or Operator RBAC. Every state-changing command appends a sanitized management audit event so operational authority is traceable without transferring ownership of a User's Personal Workspace.
