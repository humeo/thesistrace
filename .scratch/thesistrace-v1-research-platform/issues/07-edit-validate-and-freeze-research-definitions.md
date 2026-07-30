# 07 — Edit, validate, and freeze Research Definitions

**What to build:** Give the operator one structured Research Definition Draft
editor that validates the complete V1 research and atomically freezes its exact
inputs when Run is requested.

**Blocked by:** 01 — Start the empty Web Workspace; 04 — Publish Calendar, Universe, Industry, and Field Catalog.

**Status:** ready-for-agent

- [ ] Drafts can be created, edited, listed, and inspected without mutating frozen versions.
- [ ] The editor covers hypothesis, Release selection, Universe, Alpha, neutralization, Holdings Count, Rebalance Interval, Initial Cash, execution, costs, and risk-free rate.
- [ ] Structural, field, Release-availability, cross-field, and numeric-contract errors are returned together with stable locations and reason codes.
- [ ] Run-time freezing resolves `latest`, stable field identities, semantic versions, and the Numeric Execution Contract atomically.
- [ ] Validation failure creates neither a frozen Definition nor a ResearchRun and leaves the Draft editable.
- [ ] Later Draft edits cannot alter prior frozen content or hashes.
- [ ] The UI exposes no separate Freeze action, DSL, AST, or compiled-plan resource.
