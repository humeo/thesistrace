---
status: accepted
---

# Add one cross-sectional rank Builtin for Composite Alpha

The initial executable financial slice adds `cs_rank(x)` as one stable Alpha
Builtin with signature `Numeric Series -> Numeric Series`. For each Research
Session it considers only finite child values inside the ResearchRun's selected
Liquidity Universe, assigns ties their average ordinal rank, maps ranks linearly
to the inclusive range 0 through 1, and returns 0.5 when exactly one value is
valid. Missing Alpha Values remain missing and are excluded from the rank
denominator. `cs_rank` preserves its child's Effective Alpha Lookback; lower-is-
better inputs must be negated explicitly, and configured Industry
Neutralization remains a post-expression step.

This is an additive Alpha Language extension under ADR-0159 and supersedes only
ADR-0028's exclusion of cross-sectional rank. Cross-sectional standardization,
correlation, covariance, regression, implicit factor normalization, and a
separate multi-factor model or factor-list resource remain excluded. A
Composite Alpha expresses its fields, transformations, ranks, signs, and
literal weights in one frozen Alpha Formula. The Alpha Execution Plan evaluates
each child once and ranks complete session cross-sections; ResearchRun and
DailyTrack use the same Builtin Definition and exact numeric contract.
