---
status: accepted
---

# Freeze the Data Generation at ResearchRun admission

Authoritative ResearchRun admission selects the current complete Data
Generation and freezes its root Manifest digest, identity, Coverage, and Field
availability beside the compiled Alpha Expression and immutable Run input. The
queued Run retains that root; claim replaces the retention with an Attempt pin,
and every infrastructure retry pins the same root.

Queue delay, Worker loss, and concurrent Market or Financial Refresh therefore
cannot silently change the admitted calculation. Private checkpoint recovery
may resume completed chunks but cannot select another Generation, and terminal
success, failure, or cancellation releases execution ownership.

DailyTrack uses a different boundary: each new Tracking Advance Attempt pins
the then-current complete Generation while previously published Tracking state
remains unchanged. Freezing ResearchRun inputs at admission is worth the
retention cost because one admitted Run should remain one reproducible research
question.
