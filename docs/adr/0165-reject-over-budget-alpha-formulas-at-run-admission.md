---
status: superseded by ADR-0194
---

# Reject over-budget Alpha Formulae at Run admission

Alpha compilation applies deterministic structural limits for source length,
expression node count, nesting depth, and the existing 252-session Effective
Alpha Lookback. Run admission additionally estimates execution work from each
Builtin Definition's cost rule and the selected research dates and Universe,
and creates no ResearchRun when any Alpha Admission Budget is exceeded. The
Browser Draft remains local and authoring preview returns diagnostics. Concrete
thresholds are selected from representative Benchmarks, committed as constants,
and protected by boundary and performance-regression tests rather than chosen
speculatively. Worker time and memory limits remain final containment controls,
not the normal mechanism for rejecting an expensive Formula.
