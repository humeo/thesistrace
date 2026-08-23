---
status: accepted
---

# Pin one canonical numeric execution and serialization contract

Every ResearchRun immutable input and DailyTrack records one exact Numeric
Execution Contract that defines exact integer counts, deterministic
accounting-decimal arithmetic, IEEE 754 binary64 boundaries, and canonical
serialization independently of language or library defaults. Refreshed market
data affects only calculations first performed from the later Data Generation;
it does not rewrite published Track history. The active runtime has one such
contract and never dispatches across historical versions; ADR-0211 governs a
result-changing hard cut.
