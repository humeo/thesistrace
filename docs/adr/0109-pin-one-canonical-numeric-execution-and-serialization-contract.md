---
status: accepted
---

# Pin one canonical numeric execution and serialization contract

Every ResearchRun immutable input and DailyTrack pins one versioned Numeric
Execution Contract that defines exact integer counts, deterministic
accounting-decimal arithmetic, IEEE 754 binary64 boundaries, and canonical
serialization independently of language or library defaults. Refreshed market
data affects only calculations first performed from the later Data Generation;
it does not rewrite published Track history. A result-changing calculation
kernel or numeric-contract change requires a new Tracking Generation and full
execution because it changes research semantics.
