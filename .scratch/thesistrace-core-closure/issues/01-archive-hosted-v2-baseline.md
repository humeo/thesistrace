# 01 — Archive the Hosted V2 baseline

**What to build:** Preserve one recoverable Git snapshot of the complete Hosted
V2 implementation before any Hosted or legacy contraction begins.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

**Implementation:** complete

- [x] An archive manifest identifies the Hosted source, tests, deployment
  assets, runbooks, ADRs, research, and relevant untracked material included in
  the snapshot.
- [x] `refs/archive/hosted-v2-pre-core-closure` points to an immutable commit
  containing every selected item without unrelated Core work.
- [x] Restoring the ref into a clean worktree reproduces the manifest.
- [x] The ref, commit, manifest, and recovery result are recorded in Comments.
- [x] Creating the archive does not change the active product runtime.

**How to verify:**

Run the following from the repository root. It uses one fixed temporary path,
fails if that path already exists, proves the restored worktree is clean,
checks every manifest category plus all explicit additions, proves the Core
exclusions are absent, and removes the verification worktree only after every
assertion succeeds.

```sh
set -eu
restore_dir=/private/tmp/thesistrace-hosted-v2-restore
test ! -e "$restore_dir"
test "$(git show-ref --hash refs/archive/hosted-v2-pre-core-closure)" = \
  2884f96ecd1f3aed1e16b00116d54a99c9def89a
git worktree add --detach "$restore_dir" \
  refs/archive/hosted-v2-pre-core-closure
test -z "$(git -C "$restore_dir" status --short)"

for required_path in \
  docs/archive/hosted-v2-pre-core-closure.md \
  .scratch/thesistrace-hosted-platform-v2/spec.md \
  .scratch/thesistrace-hosted-platform-v2/research/bff-postgres-session-csrf-libraries.md \
  src/thesistrace/hosted/runtime.py \
  tests/hosted/test_compose_stack.py \
  deploy/hosted/compose.yaml \
  docs/runbook/hosted-compose.md \
  docs/adr/0110-make-personal-workspace-the-first-hosted-tenant-boundary.md \
  docs/adr/0150-separate-insforge-identity-from-thesistrace-auth-sessions.md \
  docs/research/2026-08-03-insforge-use-cases-and-reference-architecture.md \
  scripts/hosted-stack \
  web/e2e-hosted/hosted-acceptance.spec.ts \
  CONTEXT.md \
  pyproject.toml; do
  test -e "$restore_dir/$required_path"
done

for excluded_path in \
  .scratch/thesistrace-core-closure/spec.md \
  docs/adr/0151-make-module-first-core-the-only-active-runtime.md \
  docs/architecture/core.md; do
  test ! -e "$restore_dir/$excluded_path"
done

git worktree remove "$restore_dir"
```

## Comments

- Archived ref: `refs/archive/hosted-v2-pre-core-closure`
- Archive commit: `2884f96ecd1f3aed1e16b00116d54a99c9def89a`
- Archive tree: `9c91011044469c5519b7c8af534e0b29bae17104`
- Tracked-tree base: `f0a16066fc85a8b80fb26964a2ff265ee8627509`
- Manifest: `docs/archive/hosted-v2-pre-core-closure.md`
- Recovery result: restored the archive commit into the clean detached
  worktree `/private/tmp/thesistrace-hosted-v2-restore`; the worktree was clean,
  every representative manifest category and explicit addition was present,
  and all listed Core-closure exclusions were absent. The temporary worktree
  was then removed.
- Runtime result: the archive was assembled with an isolated temporary Git
  index. No file under `src/`, `tests/`, `web/`, `deploy/`, or `scripts/`, and no
  active build or dependency file, was changed in the current worktree.
