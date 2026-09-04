# Ship selected question composer A

**Status:** complete

## Context

See ../spec.md. Prototype decision source: branch `codex/ask-user-prototype`,
commit `68d65fe5f18a467bb7f89af45b07b598d902053c`.

## Acceptance

- [x] One bottom question surface, selectable options, custom answer and Stop.
- [x] Single/multiple/free-text questions; options plus note and custom-only.
- [x] No duplicated interactive timeline form; accepted answer is a user message.
- [x] Same Turn, immutable settings, idempotent acceptance and safe recovery.
- [x] Keyboard, IME, focus, mobile/long-content layout and compact actions.
- [x] Focused Agent/Web tests and isolated integration/E2E pass.
- [x] Reviewed, committed; prototype and parallel main changes preserved.

## Comments

### 2026-09-04 — production rewrite and verification

- Web typecheck and shell suite: 298 passed. Agent typecheck and unit suite:
  519 passed; eval preflight: 11 passed; real PostgreSQL integration: 64 passed.
- Desktop/390px browser layout and interaction suite: 8 passed. Evidence:
  `/private/tmp/ask-user-layout-fixed`.
- Isolated full-stack reload/Answer/same-Turn E2E passed in run
  `20260904t081350z-32546-d6c5b92c`. The final-image rerun also passed:
  `20260904t082707z-37226-785b0b2b` (12-second Playwright phase, exit 0,
  privacy scan and isolated environment cleanup both passed).
  Screenshot and report are retained under that run's `.local/test-runs`
  evidence directory.
- Agent production-image smoke passed in isolated project
  `thesistrace-agent-test-20260904t082400z-36221-a7ea8a27`.
- Review findings fixed with failing tests first: reject unknown selections
  before opening the resume stream (and revalidate under the database lock);
  prevent the outer question panel from scrolling when focusing a late option;
  keep staged prompt editing separate from a pending answer.
- Answer selections/text remain until authoritative receipt acceptance. An
  unfinished next-prompt draft is restored after answering, never submitted as
  the answer. No real-user question was answered or stopped during verification.
- No prototype route, demo data, dependencies, schema changes or compatibility
  path were introduced. Main and prototype worktrees were left untouched.
- Full repository `pnpm check` / `pnpm check:release` are outside this scoped
  verification; this is not a release or deployment claim.

### Delivery

Functional commit: `9897ebf` on `codex/ask-user-composer`. All review findings
above are closed and the feature's scoped verification passed. The prototype
remains clean on its separate branch. No merge into main or dev-service update
was performed; Web and Agent must be deployed together for the hard-cut Answer
envelope.

### 2026-09-04 — merged into local main

- Rebased the two unpublished feature commits onto main `d1ca2b8`; range-diff
  confirmed unchanged patches. Functional commit `9897ebf` is now `27a36b8`,
  and its delivery record is `8febbef`. Fast-forwarded main to `8febbef`.
- Temporarily stashed only `web/src/styles.css` and
  `web/e2e-core/chat-composer-layout.spec.ts`, then restored them without
  conflicts. All 159 original dirty paths, the complete unstaged patch, and
  staged state matched the pre-merge snapshot; every unrelated file hash
  matched. The verified temporary stash was removed, with all four previous
  stashes retained.
- Revalidated the actual main checkout after restoring its existing changes:
  Web typecheck and 302 shell tests; Agent typecheck and 519 unit tests; 64 real
  PostgreSQL integration tests; 8 desktop/mobile composer browser tests;
  `git diff --check`. All passed.
- Browser evidence: `/private/tmp/ask-user-main-merge-layout`. Isolated database
  project: `thesistrace-agent-test-20260904t084300z-45238-dca5d356`, cleaned up
  successfully by the test runner.
- No remote push, branch/worktree removal, or explicit dev-service restart.
  The earlier branch E2E and image-smoke evidence remains separate from these
  post-merge checks; no full release gate is claimed.
