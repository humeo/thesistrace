---
status: accepted
---

# Admit long Research by peak execution footprint, not total work

ResearchRun admission keeps deterministic structural limits for Alpha source
length, expression node count, nesting depth, and Effective Alpha Lookback. It
also rejects a Run when the smallest semantics-preserving bounded execution
slice cannot fit the configured Worker safety envelope. Cross-sectional
operations such as `cs_rank` therefore require one complete eligible Universe
for one Research Session inside that minimum slice.

Estimated Total Research Work is retained for progress, duration guidance, and
user warning, but it cannot reject a Run or change queue priority merely because
the selected Research Period is long. A Research Period from 2010 through the
latest covered session is consequently admissible when its Formula is
structurally valid and its minimum legal execution slice fits the peak safety
limit; it may take longer or wait behind earlier admitted work without becoming
an invalid research question.

This supersedes ADR-0165's hard rejection by total estimated execution work.
Worker memory and time limits remain final containment controls rather than the
normal path for rejecting long Research.
