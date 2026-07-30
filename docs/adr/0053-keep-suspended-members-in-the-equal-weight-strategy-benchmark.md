---
status: accepted
---

# Keep suspended members in the equal-weight Strategy Benchmark

For the Strategy Benchmark return ending on one market session, a member
confirmed `full_session_suspended` on that session contributes zero return and
remains in the equal-weight denominator. Its weight is not redistributed to
members having a market bar.

When a valid Adjusted Research Price reappears, that member's benchmark return
recognizes the complete change from its last valid mark. The Benchmark does not
simulate execution, Board-Lot Rounding, or Transaction Costs.

Only a confirmed suspension permits this zero-return carry. An unexplained
missing market observation is a data-quality failure and is never silently
treated as a suspended member.

A partial suspension with a valid daily bar uses its observed Adjusted Research
Price return and does not receive a zero-return carry.

ADR-0101 resolves an absent ending Open only on demand. Explicit effective
terminal delisting after a valid starting mark supplies a synthetic terminal
value of zero and a `-100%` member return. This is distinct from suspension
carry and from an unexplained missing observation.
