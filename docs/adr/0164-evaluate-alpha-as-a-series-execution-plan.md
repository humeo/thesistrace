---
status: accepted
---

# Evaluate Alpha as a Series execution plan

The Worker derives one transient deterministic post-order Alpha Execution Plan
from the frozen canonical Alpha Expression. Each plan node computes its
complete Numeric Series once for the execution slice, and each rolling Builtin
uses a one-pass series algorithm rather than recursively reevaluating its child
for every cell in every window. ResearchRun evaluates the required research
slice, while DailyTrack evaluates only the Effective Alpha Lookback plus new
Research Sessions through the same planner and Builtin evaluators. The plan is
neither persisted nor treated as another execution truth, and ThesisTrace does
not introduce a general bytecode virtual machine.
