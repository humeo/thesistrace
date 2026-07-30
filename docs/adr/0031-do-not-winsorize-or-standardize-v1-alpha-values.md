---
status: accepted
---

# Do not winsorize or standardize V1 Alpha Values

V1 applies no automatic winsorization, clipping, rank transformation, or
cross-sectional standardization to valid Alpha Expression outputs. If a frozen
Research Definition selects `industry` neutralization, the runtime directly
subtracts the selected industry's equal-weight mean after the eligibility and
coverage gates defined by ADR-0077. If it selects `none`, the eligible valid
outputs are the final Alpha Values.

This keeps the transformation visible and bounded: Alpha Expression evaluation,
strict missing-value handling, and then the one selected neutralization option.
Any future outlier or standardization treatment must be introduced as an
explicit, versioned decision rather than silently changing existing runs.
