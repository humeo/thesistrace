# 39 — Remove the old Web and authentication surface

**What to build:** Delete the now-inactive monolithic Web, old routes, and
Hosted authentication wrapper after the replacement Shell is accepted.

**Blocked by:** 01, 38.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before any old surface is deleted.
- [ ] Old routes, monolithic navigation, authentication wrapper, Workspace
  Dashboard, Operations Ledger, raw JSON popup, and download surface are gone.
- [ ] Draft, frozen version, Result, Attempt, Generation, Advance, Checkpoint,
  Local/Hosted label, and deployment controls have no active page or URL.
- [ ] No feature flag, fallback route, or alternate bundle can restore the old
  product surface.
- [ ] The seven stable URLs and complete Core browser flow behave identically
  after deletion.
- [ ] Backend Hosted and legacy removal remain outside this ticket.

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
  web/playwright.config.ts \
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
./scripts/core-test-runtime run uv run pytest -q \
  tests/architecture/test_core_runtime_boundaries.py \
  tests/acceptance/test_core_backend_cutover.py
./scripts/core-test-runtime run bun run --cwd web test:e2e
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
