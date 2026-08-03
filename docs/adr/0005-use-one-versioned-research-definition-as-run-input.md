---
status: superseded by ADR-0151
---

# Use one versioned Research Definition as run input

ThesisTrace V1 describes a complete research in one versioned structured
Research Definition. After structural and semantic validation, that same
document is frozen and consumed directly by ResearchRun; the system does not
introduce a Research DSL, AST, compiler, or separate compiled plan. Parsing an
Alpha Expression remains an independent, bounded formula-engine concern
defined by ADR-0027. This decision supersedes ADR-0004 while preserving one
shared research definition format for Factor Evaluation, Strategy Backtest,
and the Daily Tracking path introduced by ADR-0102.

ADR-0098 keeps the authoring revision mutable as a Research Definition Draft
and automatically creates the immutable frozen version when the operator
requests Run. V1 exposes no separate Freeze action.
