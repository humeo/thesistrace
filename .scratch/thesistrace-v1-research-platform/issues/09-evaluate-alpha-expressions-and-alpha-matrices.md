# 09 — Evaluate Alpha Expressions and Alpha Matrices

**What to build:** Validate and execute the complete bounded Alpha Expression
language over a pinned Dataset Release and emit one deterministic Final Alpha
Cross-Section per Research Session.

**Blocked by:** 04 — Publish Calendar, Universe, Industry, and Field Catalog; 07 — Edit, validate, and freeze Research Definitions; 08 — Fix numeric execution and canonical serialization.

**Status:** resolved

- [x] The parser accepts only the six fields, numeric literals, parentheses, arithmetic, and the closed scalar, lag, change, and rolling function set.
- [x] Every window argument is a literal integer from 1 through 252 and composed Effective Alpha Lookback never exceeds 252.
- [x] Evaluation uses binary64, natural logarithm, three-valued sign, population rolling standard deviation, and complete ordered windows.
- [x] Missing operands, incomplete windows, division by zero, invalid logarithms, and non-finite results propagate Missing with explicit coverage reasons.
- [x] Point-in-time Universe and ST gates run before optional industry coverage, minimum group size, and equal-weight demeaning.
- [x] No implicit clipping, winsorization, ranking, standardization, or Alpha-direction reversal occurs.
- [x] Canonical Instrument Identity ordering makes every Alpha Matrix checksum deterministic.

## Comments

- Added the bounded parser/direct evaluator, static Effective Lookback,
  strict-Missing float64 operations, point-in-time eligibility gates, optional
  L1 industry demeaning, coverage loss, and deterministic matrix checksum.
- Public kernel tests cover forbidden syntax, window composition, invalid
  arithmetic, rolling semantics, ordering, and neutralized group sums.
