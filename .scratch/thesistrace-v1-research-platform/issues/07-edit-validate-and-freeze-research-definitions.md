# 07 — Edit, validate, and freeze Research Definitions

**What to build:** Give the operator one structured Research Definition Draft
editor that validates the complete V1 research and atomically freezes its exact
inputs when Run is requested.

**Blocked by:** 01 — Start the empty Web Workspace; 04 — Publish Calendar, Universe, Industry, and Field Catalog.

**Status:** resolved

- [x] Drafts can be created, edited, listed, and inspected without mutating frozen versions.
- [x] The editor covers hypothesis, Release selection, Universe, Alpha, neutralization, Holdings Count, Rebalance Interval, Initial Cash, execution, costs, and risk-free rate.
- [x] Structural, field, Release-availability, cross-field, and numeric-contract errors are returned together with stable locations and reason codes.
- [x] Run-time freezing resolves `latest`, stable field identities, semantic versions, and the Numeric Execution Contract atomically.
- [x] Validation failure creates neither a frozen Definition nor a ResearchRun and leaves the Draft editable.
- [x] Later Draft edits cannot alter prior frozen content or hashes.
- [x] The UI exposes no separate Freeze action, DSL, AST, or compiled-plan resource.

## Comments

- Added durable Draft CRUD, aggregate validation, Release/field resolution,
  Run-time atomic freeze, semantic/numeric pinning, immutable versions, and
  idempotent queued Run creation.
- Browser acceptance edits and saves a Draft, then creates a Run that
  automatically freezes version 1; there is no separate Freeze action.
