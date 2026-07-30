# 09 — Evaluate Alpha Expressions and Alpha Matrices

**What to build:** Validate and execute the complete bounded Alpha Expression
language over a pinned Dataset Release and emit one deterministic Final Alpha
Cross-Section per Research Session.

**Blocked by:** 04 — Publish Calendar, Universe, Industry, and Field Catalog; 07 — Edit, validate, and freeze Research Definitions; 08 — Fix numeric execution and canonical serialization.

**Status:** ready-for-agent

- [ ] The parser accepts only the six fields, numeric literals, parentheses, arithmetic, and the closed scalar, lag, change, and rolling function set.
- [ ] Every window argument is a literal integer from 1 through 252 and composed Effective Alpha Lookback never exceeds 252.
- [ ] Evaluation uses binary64, natural logarithm, three-valued sign, population rolling standard deviation, and complete ordered windows.
- [ ] Missing operands, incomplete windows, division by zero, invalid logarithms, and non-finite results propagate Missing with explicit coverage reasons.
- [ ] Point-in-time Universe and ST gates run before optional industry coverage, minimum group size, and equal-weight demeaning.
- [ ] No implicit clipping, winsorization, ranking, standardization, or Alpha-direction reversal occurs.
- [ ] Canonical Instrument Identity ordering makes every Alpha Matrix checksum deterministic.
