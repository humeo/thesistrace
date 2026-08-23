---
status: accepted
---

# Do not winsorize or standardize V1 Alpha Values

V1 applies no automatic winsorization, clipping, rank transformation, or
cross-sectional standardization to valid Alpha Expression outputs. If immutable
ResearchRun input selects `industry` neutralization, the runtime directly
subtracts the selected industry's equal-weight mean after the eligibility and
coverage gates defined by ADR-0077. If it selects `none`, the eligible valid
outputs are the final Alpha Values.

This keeps the transformation visible and bounded: Alpha Expression evaluation,
strict missing-value handling, and then the one selected neutralization option.
Adding an outlier or standardization treatment is a result-changing Alpha
Language hard cut, never an implicit change to accepted ResearchRuns.
