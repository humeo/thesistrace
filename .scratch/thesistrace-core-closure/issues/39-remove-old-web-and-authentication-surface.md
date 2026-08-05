# 39 — Remove the old Web and authentication surface

**What to build:** Delete the now-inactive monolithic Web, old routes, and
Hosted authentication wrapper after the replacement Shell is accepted.

**Blocked by:** 01, 38.

**Status:** complete

**Implementation:** complete

- [x] The Hosted archive ref is reverified before any old surface is deleted.
- [x] Old routes, monolithic navigation, authentication wrapper, Workspace
  Dashboard, Operations Ledger, raw JSON popup, and download surface are gone.
- [x] Draft, frozen version, Result, Attempt, Generation, Advance, Checkpoint,
  Local/Hosted label, and deployment controls have no active page or URL.
- [x] No feature flag, fallback route, or alternate bundle can restore the old
  product surface.
- [x] The seven stable URLs and complete Core browser flow behave identically
  after deletion.
- [x] Backend Hosted and legacy removal remain outside this ticket.

**How to verify:**

Run the deletion checks and the unchanged Core flow against the archived
baseline plus isolated PostgreSQL and RustFS. The trap must remove the runtime
even if a later check fails:

```sh
set -eu
archive_commit=2884f96ecd1f3aed1e16b00116d54a99c9def89a
test "$(git show-ref --hash refs/archive/hosted-v2-pre-core-closure)" = \
  "$archive_commit"
git cat-file -e "$archive_commit:web/src/App.tsx"
git cat-file -e "$archive_commit:web/src/hostedAuth.tsx"

for removed_path in \
  web/core.html \
  web/e2e \
  web/e2e-hosted \
  web/playwright.core-shell.config.ts \
  web/playwright.hosted.config.ts \
  web/src/App.tsx \
  web/src/hostedAuth.tsx \
  web/src/shell/main.tsx; do
  test ! -e "$removed_path"
done

./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
bun run --cwd web typecheck
bun run --cwd web build
bun run --cwd web test:shell
./scripts/core-test-runtime run bun run --cwd web test:e2e
./scripts/core-test-runtime run uv run pytest -q \
  tests/architecture/test_core_runtime_boundaries.py \
  tests/acceptance/test_core_backend_cutover.py
```

The active Web tree and `package.json` must contain no import, script, Vite
entry, Playwright project, feature flag, or fallback route for the deleted
application or authentication boundary. The production build must still emit
only `index.html` and one four-resource product bundle. The browser suite must
repeat the seven stable URLs and complete Core flow without any old workspace,
authentication, Hosted, operations, raw JSON, download, deployment, Draft,
frozen-version, Attempt, Generation, Advance, or Checkpoint page or URL.

The architecture and backend-cutover acceptance must continue to prove that
the public HTTP inventory contains only Data, Definitions, ResearchRuns, and
DailyTracks resources. Backend Hosted and legacy source is deliberately left
for Tickets 40–44.

## Comments

- Before deletion, `refs/archive/hosted-v2-pre-core-closure` was resolved to
  `2884f96ecd1f3aed1e16b00116d54a99c9def89a`, restored into the clean detached
  worktree `/private/tmp/thesistrace-hosted-v2-restore`, and checked against all
  required and excluded paths from Ticket 01. The worktree was clean and was
  removed after verification.
- The executable post-deletion contract was committed first in `d392862`.
  `ddf6db6` then removed the old monolithic App, authentication wrapper, old
  and Hosted browser suites, second HTML/React entry, old CSS, and three
  dependencies used only by that surface: about `5,000` lines in total.
- The transitional Playwright selector was contracted to one standard
  `playwright.config.ts` and one `test:e2e` command. Vite has one production
  `index.html` input and explicitly returns `404` for the removed
  `/core.html`, so its SPA fallback cannot revive the old entry.
- The exact command in **How to verify** passed after placing the empty-state
  browser flow before the backend acceptance that rebuilds schemas. The result
  was TypeScript/build/Shell green, `18 passed` browser flows in `1.9m`, and
  `22 passed, 1 warning in 20.68s` for architecture plus backend cutover. The
  production build emitted only `dist/index.html` and one product bundle, and
  the trap removed both runtime containers.
- Review round 1 passed Standards and Spec with zero findings. It confirmed the
  fixed archive ref, complete Web/Auth deletion, single entry/configuration,
  explicit old-entry rejection, unchanged seven stable URLs and Core journey,
  and that no backend Hosted or legacy source was deleted ahead of Tickets
  40–44.
