---
status: accepted
---

# Make Personal Workspace the first hosted tenant boundary

ThesisTrace's first hosted multi-user release gives every authenticated User exactly one private Personal Workspace and uses it as the ownership, quota, and scheduling-isolation boundary for private research resources, while excluding Organizations, shared Personal Workspaces, additional members, and collaboration. This is the smallest tenant model that provides hosted isolation and supersedes ADR-0096 only for the hosted product; platform-owned Dataset Releases remain outside Personal Workspace ownership.
