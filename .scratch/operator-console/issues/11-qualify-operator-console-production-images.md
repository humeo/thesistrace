# 11 — Qualify the Operator Console in final Production Images

**What to build:** Prove that the complete Operator Console, Auth/Core authority
split, durable Worker, and secret boundary work together in the exact final image
topology that will be deployed.

**Blocked by:** 03 — Revoke another Researcher's Login Sessions; 10 — Retain
operation receipts without retaining Data Generations.

**Status:** complete

## Implementation Plan

1. Extend the final-image harness with a private, file-backed Operator fixture
   that creates an initial Operator, a transfer target, and a revocation target
   without exposing Cookies or passwords in evidence. Qualify assignment,
   ordinary-Researcher `404`, exact Proof consumption, Invitation issue/reissue,
   other-Researcher Session revocation, atomic transfer, and preserved new-
   Operator access through Caddy.
2. Before the Data Operator Worker starts, submit one replay-backed Market
   Refresh through the Operator APIs and prove Core returns a durable `accepted`
   receipt while status reports the Worker unavailable. Prove missing and
   placeholder Worker credentials fail before execution, then start exactly one
   long-running non-`--once` Worker and observe the accepted receipt complete.
3. Age that terminal qualification receipt through a test-only fixture, run the
   final-image private Garbage Collection command, and prove the receipt is
   removed without changing the current Dataset Head. Keep static architecture
   assertions for the one-service, one-replica, Worker-only Secret topology and
   the absence of a production one-shot or per-kind execution path.
4. Run the existing end-to-end Operator Console workflow as an explicit
   Production Image Smoke phase. Extend it with desktop, collapsed-sidebar,
   tablet, mobile-drawer, keyboard/focus/Escape, reduced-motion, touch-target,
   accessible-name, narrow-field, and non-color-state assertions while retaining
   its real PostgreSQL/RustFS, Resend fake, and versioned replay coverage for all
   three Refresh kinds, FIFO, outcomes, status, Cancel, Retry, and Worker
   recovery.
5. Update the Production and Data Operator runbooks for singleton assignment and
   transfer, supported Console operations, accepted-versus-published semantics,
   the single Worker and Secret boundary, recovery, offline qualification, and
   diagnostic artifacts. Add/adjust low-cost contract tests first, run focused
   Auth/Core/Web checks, then run the complete `pnpm check:release` gate against
   the final changes.

## Acceptance Criteria

- [x] Final Auth, Core, Data Operator Worker, Web, Caddy, PostgreSQL, and RustFS
  images start, become healthy, and expose only their intended public and private
  boundaries.
- [x] The final topology contains exactly one always-running, single-slot Data
  Operator Worker and no obsolete one-shot or parallel Refresh execution path.
- [x] Production Image Smoke proves Operator assignment and transfer,
  ordinary-Researcher `404`, Operator Proof consumption, Invitation issue and
  reissue, other-Researcher Session revocation, and preserved Operator access.
- [x] Production Image Smoke proves Market, Financial, and Industry submission,
  global FIFO execution, publication/no-change/degraded outcomes, Dataset Head
  status, Cancel, Retry, Worker restart recovery, and receipt cleanup.
- [x] The Tushare Secret exists only in the Worker environment, never appears in
  logs or responses, and a missing or placeholder value fails Worker startup
  without breaking durable submission through healthy Core.
- [x] Real browser E2E through Caddy uses one Operator and one ordinary
  Researcher, real PostgreSQL and RustFS, a Resend fake, and versioned Tushare
  replay to cover every critical user workflow.
- [x] Browser acceptance covers desktop, collapsed sidebar, tablet, mobile
  navigation drawer, keyboard-only operation, focus containment and restoration,
  Escape behavior, reduced motion, accessible names, touch targets, and
  non-color-only state.
- [x] The Console follows the repository's dense, dark product workbench without
  adding a generic administration dashboard, light-theme fallback, or hidden
  critical provenance.
- [x] Ordinary qualification uses no public internet and no live Tushare request;
  live Tushare verification remains a separate explicit gate.
- [x] The deployment and operational documentation describes the new Worker,
  assignment/transfer commands, secret boundary, submission-versus-publication
  distinction, recovery behavior, and supported Console operations.
- [x] The complete local release command passes against committed final changes,
  and diagnostic artifacts identify image versions, operation IDs, request IDs,
  logs, responses, and browser screenshots on failure.

## Verification

- The pre-commit `pnpm check:release` gate passed in full: Ruff, 931 Python
  tests, both TypeScript typechecks, 171 Auth tests, and 148 Web tests. The only
  Python warning was the existing local-lifecycle `forkpty()` deprecation.
- Core integration run `20260830t183336z-41563-73166e05` passed 416 primary
  PostgreSQL/RustFS tests, with eight marker-selected tests deferred, followed
  by all six independent database/dependency restart phases. Auth integration
  run `20260830t185209z-61698-f5d5a08e` passed 128 tests.
- Real Caddy browser run `20260830t185305z-62112-d434b341` passed all 16 tests
  in 4.0 minutes, including the final mobile focus-containment fix.
- Production Image Smoke run `20260830t185810z-64937-0988f5f1` reported status
  zero for every phase. It proved assignment, ordinary-Researcher `404`, exact
  single-use Proof consumption, Invitation issue/reissue, other-Researcher
  Session revocation, atomic transfer, queued submission without a Worker,
  Worker-only credentials, one continuous Worker, processing and publication,
  and receipt cleanup without changing the Dataset Head. The explicit Operator
  browser phase passed in 94 seconds, covering all three Refresh kinds, FIFO,
  outcomes, status, Cancel, Retry, recovery, and responsive accessibility.
- The separate Auth image run `20260830t190914z-68576-7e666766` and Caddy image
  run `20260830t190936z-68794-c4c37a1c` also passed. Runtime-secret cleanup,
  Compose cleanup, and overall status were zero for the Core integration,
  browser, and image runs. Evidence remains under each isolated run directory;
  no live Tushare or public Resend request was used.
- The first committed-code gate at `6d556de` stopped with one failing document
  contract and 930 passing Python tests. A final Markdown line wrap had split
  the unchanged deactivation-boundary sentence across two lines. The exact
  failing test reproduced in 0.04 seconds; reading the same confirmed worktree
  file with whitespace folded preserved the full required sentence. The test
  now normalizes whitespace before checking every original boundary phrase.
  The narrow regression passed, Ruff passed, and all 74 lifecycle tests passed
  in 104.70 seconds. No production code or authorization rule changed.

### Final committed-code gate

- `pnpm check:release` passed with exit status zero at
  `9faef367b23b76323fbdf2187d96889d66e600b3`. The worktree was clean before and
  after the command. Implementation commit `6d556de` and document-contract
  correction `9faef36` were both committed before this run; the subsequent
  completion record changes only this issue and the feature spec.
- Ruff, both TypeScript typechecks, 931 Python tests, 171 Auth tests, and 148 Web
  tests passed. The sole Python warning remains the pre-existing `forkpty()`
  deprecation.
- Core run `20260830t192123z-850-6b92b90e` passed 416 primary real-dependency
  tests in 885.53 seconds, with eight marker-selected tests deferred, followed
  by all six independent restart/recovery phases. Auth integration run
  `20260830t193917z-17585-171bd0e2` passed all 128 tests.
- Real Caddy browser run `20260830t194044z-18410-cdd84467` passed all 16 tests
  in 5.4 minutes, including the complete Operator workflow and keyboard,
  mobile-drawer, and touch-target acceptance.
- Final Production Image run `20260830t194654z-23136-eb74a984` passed all 86
  recorded phases. Its separate Operator browser phase passed in 92 seconds.
  Evidence confirms ordinary-Researcher `404`, one-time Proof consumption,
  durable acceptance while the Worker is unavailable, successful publication,
  former-Operator Session revocation, successor access, receipt removal, and
  an unchanged Dataset Head after collection.
- The separate Auth image run `20260830t200000z-28517-5a4f25a2` and Caddy image
  run `20260830t200029z-28721-2c47039d` passed. Core integration, browser, and
  image metadata all record the exact committed revision,
  `git_worktree_dirty=false`, every phase at status zero, successful runtime-
  secret cleanup, successful Compose cleanup, and overall status zero.

## Review

- Standards review found a mobile-navigation focus-containment gap. The drawer
  now exposes its modal semantics, cycles Tab and Shift+Tab inside its links
  and controls, handles Escape, and restores focus to the trigger. Browser
  acceptance proves both wrap directions. Re-review found no remaining
  Standards findings.
- Spec review passed: the singleton capability and Auth/Core authority split,
  exact password Proof, one global FIFO, accepted-versus-published distinction,
  safe operational status, recovery, receipt retention, Worker-only Secret,
  responsive shell, and private-only exceptional operations all retain their
  agreed boundaries. No fallback, migration, compatibility, per-kind Worker,
  deactivation UI, or unified audit surface was introduced.
- Qualification exposed stale fixture assumptions around the Dataset baseline
  and graceful Worker shutdown. The image browser now starts from a fresh,
  run-scoped dataset and prepares both Market and Financial boundaries.
  SIGTERM stops the Worker after its current attempt and releases its lease;
  browser fixtures assert the release rather than expiring an already-released
  lease. Retry exhaustion uses its own genuinely running, expired receipt and
  never rewrites a successfully published receipt into failure. Unit, full
  browser, and final-image checks pass with these corrections.
- The post-commit document-contract correction was reviewed against Standards
  and Spec: it removes sensitivity to Markdown line wrapping without removing
  or weakening any required operational-boundary phrase. No review finding
  remains; the full committed-code gate subsequently passed at `9faef36`.

## Comments

- 2026-08-31: Completed implementation, qualification fixes, Standards/Spec
  review, and the pre-commit full release gate. Commit the implementation before
  rerunning the exact release command on a clean revision; record completion
  only after that final committed-code gate passes.
- 2026-08-31: The first committed-code gate caught a line-wrap-sensitive runbook
  assertion. Reproduced it, normalized only the test's whitespace handling,
  passed the regression and all lifecycle tests, and re-reviewed the correction
  before a separate Ticket 11 fix commit and another clean release gate.
- 2026-08-31: The full release gate passed against clean commit `9faef36`,
  including real dependency recovery, all 16 browser tests, all 86 final-image
  phases, and the separate Auth/Caddy image checks. All acceptance criteria and
  review findings are closed. Marked this issue complete with a documentation-
  only completion record; the qualified implementation remains unchanged.
