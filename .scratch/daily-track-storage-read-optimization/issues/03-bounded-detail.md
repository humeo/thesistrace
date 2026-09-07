# 03 — bounded-detail

Status: ready-for-agent

Implement item 03 of ../spec.md and its relevant acceptance requirements.

## Acceptance

- [x] Implement current contracts without compatibility or migration.
- [x] Run relevant behavior and real-dependency verification.
- [x] Resolve Standards and Spec review findings.
- [x] Commit this issue independently.

## Evidence

- Shared `load_read_snapshot` selects ownership, Origin, one Head/account, unresolved work and bounded checkpoint references. Normal detail never invokes full-chain load; explicit equivalence diagnostics retain it.
- The current Dataset calendar and Track snapshot are captured in a short transaction under the existing Dataset publication guard. S3 object reads occur after release. No retry/fallback path.
- Window includes a checkpoint ending on its first day and its correcting successor. Pagination and detail overwrite older boundary observations; page cursors remain tied to Head.
- Standards and Spec reviews: each found the calendar/Head race, then confirmed its fix and the deterministic concurrent-publication regression. No remaining findings.
- Core complete integration passed 426 cases and six independent restart cases before the final gate rerun; final missing-Head predicate regression and both reviewers passed.
- Both relevant DailyTrack browser flows passed in isolated targeted runs. Final `pnpm test:image-smoke` exited 0, including Core/Auth/Agent/Caddy. See ../evidence.md for exact runs and earlier failures.
- [ ] Final `pnpm check` green: latest run exited 1 (425 Core cases passed, one activation-fixture 409 before the obsolete numeric contract assertion). A targeted reproduction passed both numeric-contract cases; the original refusal remains undiagnosed. Earlier Auth/Agent/browser transient failures are retained in the evidence and are not claimed fixed.
- Implementation is independently committed, but this issue remains ready-for-agent because the complete final gate is unresolved. No merge or deployment.
