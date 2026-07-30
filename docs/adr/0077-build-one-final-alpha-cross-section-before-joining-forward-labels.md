---
status: accepted
---

# Build one final Alpha cross-section before joining forward labels

For every signal session `t`, V1 applies this ordered pipeline:

```text
Universe Membership
-> point-in-time ST and *ST exclusion
-> Alpha Expression evaluation and invalid-value exclusion
-> optional point-in-time industry coverage and group-size gates
-> optional equal-weight industry demeaning
-> one Final Alpha Cross-Section
```

When neutralization is `none`, the industry steps are skipped. When it is
`industry`, only the valid, non-ST Alpha Expression outputs with a valid
historical industry enter an industry mean. A group with fewer than two such
instruments is excluded before demeaning. ST instruments, missing-industry
instruments, and invalid Alpha outputs therefore cannot affect another
instrument's Final Alpha Value.

Factor Evaluation joins the completed Final Alpha Cross-Section independently
to each 1-, 5-, and 20-session Forward Return Label. A missing label removes
that instrument only from that horizon's Effective Factor Sample. It does not
remove or recalculate the Final Alpha Value, alter another horizon, or change
the Alpha Values consumed by Strategy Backtest.
