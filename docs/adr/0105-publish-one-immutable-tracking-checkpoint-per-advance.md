# Publish one immutable Tracking Checkpoint per Advance

A successful Tracking Advance atomically publishes one immutable Checkpoint bound to its predecessor, frozen target sessions, Data Generation, contracts, bounded results, and terminal Strategy state. The Tracking Head moves only after complete publication, and failed Attempts expose no partial progress or cross-Attempt checkpoint.
