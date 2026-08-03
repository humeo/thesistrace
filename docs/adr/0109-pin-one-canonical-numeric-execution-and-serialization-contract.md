---
status: accepted
---

# Pin one canonical numeric execution and serialization contract

Every ResearchRun immutable input and DailyTrack pins one versioned Numeric
Execution Contract that defines exact integer counts, deterministic
accounting-decimal arithmetic, IEEE 754 binary64 boundaries, and canonical
serialization independently of language or library defaults. Historical data
corrections follow ADR-0144 in the same Tracking Generation, while a
result-changing calculation-kernel or numeric-contract change requires a new
Generation and full execution because it changes research semantics.
