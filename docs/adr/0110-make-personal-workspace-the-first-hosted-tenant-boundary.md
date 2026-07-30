---
status: accepted
---

# Make Personal Workspace the first hosted tenant boundary

ThesisTrace's first hosted multi-user release gives every authenticated User
exactly one private Personal Workspace and uses that Workspace as the ownership,
quota, and scheduling-isolation boundary for the User's research resources. It
does not introduce Organizations, shared Workspaces, additional members, or
collaboration. This supersedes ADR-0096 only for the hosted product; the
single-operator V1 Workspace remains historical context.

ADR-0111 defines Dataset Releases as shared platform resources outside Personal
Workspace ownership.
