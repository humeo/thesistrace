# 07 — Run a cs_rank Composite Alpha ResearchRun

**What to build:** Allow a researcher to submit one Alpha Formula that combines
market and financial Series through explicit arithmetic, signs, weights, and
cs_rank, then execute it through authoritative admission, a pinned
ResearchRun Attempt, the shared Series Execution Plan, and normal result
publication.

**Blocked by:** 06 — Resolve six Session-Aligned Financial Fields; external
prerequisite — Alpha Language and Research Workspace feature.

**Status:** complete

- [x] The composed Alpha Authoring Catalog exposes all six financial fields and
  one cs_rank Builtin without adding a second field allowlist.
- [x] cs_rank accepts and returns a Numeric Series and evaluates independently
  for every Research Session inside the selected Liquidity Universe.
- [x] Finite child values receive ascending average ordinal ranks mapped to the
  inclusive zero-to-one range.
- [x] Ties receive their average rank, one valid value receives 0.5, and an
  all-missing cross-section remains missing.
- [x] Missing and non-finite values are excluded from the denominator and
  remain missing at their original coordinates.
- [x] Lower-is-better behavior requires explicit Formula negation and Industry
  Neutralization remains a post-expression operation.
- [x] cs_rank preserves the child's Effective Alpha Lookback and the Execution
  Plan evaluates each child once before ranking complete cross-sections.
- [x] Authoritative admission freezes the Formula, compiled Expression,
  resolved Field References, calculation contracts, and selected Data
  Generation facts before queuing.
- [x] A financial Formula whose calculation slice exceeds Financial Coverage
  is rejected before durable queue mutation.
- [x] An otherwise equivalent market-only Formula remains admissible when
  Financial Coverage is behind.
- [x] The Worker executes the admitted Expression and pinned Generation without
  recompiling current source or consulting a mutable catalog.
- [x] One deterministic market-financial Composite Alpha completes through the
  real HTTP, database, claim, Worker, and result-publication seams.
- [x] No factor-list, factor-weight, multi-factor-model, or alternative
  financial authoring resource is introduced.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- The sibling Alpha Language and Research Workspace Spec is intentionally an
  external blocking feature rather than a duplicated mega-ticket here.
