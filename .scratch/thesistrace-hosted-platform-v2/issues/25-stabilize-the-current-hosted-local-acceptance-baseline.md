# 25 — Stabilize the Current Hosted Local Acceptance Baseline

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Turn the current partially implemented and repeatedly patched
Hosted Local Acceptance worktree into one reviewable green baseline before adding
more orchestration behavior. Preserve verified product fixes, remove stale
experiments, and establish focused tests for the boundaries already changed.

**Blocked by:** None.

**Status:** resolved

- [x] Inventory the current acceptance-related diff and classify every changed or generated artifact as a required product fix, local-acceptance foundation, diagnostic experiment, or stale output; unrelated user changes remain untouched.
- [x] Preserve and finish the focused fixes already required by observed failures, including database role and migration ordering, cross-UID Working Cache access, local Caddy denial of every `/storage/*` path, and the separation between local diagnostic evidence and production qualification evidence.
- [x] Remove or replace stale debug code, temporary artifacts, and unfinished assumptions that only work inside the previous one-shot full-run loop, without discarding a working fix merely to reduce the diff.
- [x] Focused backend, migration, Compose/configuration, Caddy/storage, acceptance-runner unit, formatting, typecheck, and lint checks pass for every boundary touched by the baseline.
- [x] The resulting diff is small enough to review as one coherent baseline and records which observed failures are fixed, which remain deliberately assigned to tickets 26–38, and which production claims remain out of scope.
- [x] No disposable acceptance process, container, network, or volume is unintentionally left running after verification, and cleanup does not remove unrelated developer data.

## Comments

- Stabilized the interrupted Hosted Local Acceptance work as one baseline: the
  observed migration/role, Working Cache, Caddy Storage, and launch-evidence
  fixes remain product changes; the local Compose overlay, runner, probes,
  ADR/runbook, and focused suites are the retained acceptance foundation. The
  former release-boundary ticket was replaced by the Launch Qualification and
  Hosted Local Acceptance split, while phase/resume/Core Session behavior stays
  assigned to tickets 26–28.
- Verification passed the local acceptance file (`21 passed`), all other
  directly changed Python test files (`75 passed, 14 skipped`), Ruff lint,
  shell syntax, Python compilation, Web typecheck, diff checks, and Compose
  configuration exercised by the focused tests. The disposable local Compose
  project had no remaining containers, volumes, or networks.
