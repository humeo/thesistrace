---
status: accepted
---

# Delete terminal private resources immediately with a Tombstone

A Personal Workspace may irreversibly delete a terminal ResearchRun or stopped DailyTrack as one complete resource, creating a permanent Resource Tombstone and removing every unreferenced private object, while nonterminal resources and retained dependencies remain protected. Physical cleanup retries idempotently and releases quota only when complete, preserving auditability without retaining a user-accessible recovery path.
