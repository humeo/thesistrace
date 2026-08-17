---
status: accepted
---

# Freeze the Data Generation at ResearchRun admission

Authoritative ResearchRun admission selects the current complete Data
Generation and freezes its root Manifest digest, identity, Coverage, and Field
availability beside the compiled Alpha and resolved Field References. The
queued ResearchRun durably retains that root. Claim atomically replaces the
retention with an Attempt pin before opening any Parquet object, and every
infrastructure retry of the same ResearchRun pins the same frozen root.

This makes the admitted calculation one immutable question: queue delay,
Worker loss, or concurrent Market or Financial Refresh cannot silently change
its inputs. A retry may recompute the complete result, but it cannot select a
different Generation. Between retryable Attempts, durable Run retention
continues to protect the root and all transitively referenced family
Manifests, Raw Evidence, table Manifests, and Parquet Objects from collection.
Terminal completion, failure, or cancellation releases execution ownership.

This decision supersedes only the then-current-Head-per-Attempt selection in
ADR-0095 and ADR-0154. Attempt state, fencing, bounded retry, result
publication, and transient artifact rules remain unchanged. DailyTrack Advance
continues to select and pin one complete current Generation for each new
progression under its own lifecycle; freezing a seed ResearchRun does not pin
all future Track advances to the seed Generation. ADR-0182 remains the
authority for user-initiated research reuse through Use as Draft rather than a
Rerun action.

## Superseded clause

ADR-0195 replaces the permission for a retry to recompute the complete result
when a valid ResearchRun checkpoint exists. Every retry still uses the frozen
Generation; it resumes from the latest valid checkpoint and starts from the
beginning only when the Run has no valid completed checkpoint.
