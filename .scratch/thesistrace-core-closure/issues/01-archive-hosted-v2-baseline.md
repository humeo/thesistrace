# 01 — Archive the Hosted V2 baseline

**What to build:** Preserve one recoverable Git snapshot of the complete Hosted
V2 implementation before any Hosted or legacy contraction begins.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] An archive manifest identifies the Hosted source, tests, deployment
  assets, runbooks, ADRs, research, and relevant untracked material included in
  the snapshot.
- [x] `refs/archive/hosted-v2-pre-core-closure` points to an immutable commit
  containing every selected item without unrelated Core work.
- [x] Restoring the ref into a clean worktree reproduces the manifest.
- [x] The ref, commit, manifest, and recovery result are recorded in Comments.
- [x] Creating the archive does not change the active product runtime.

**How to verify:**

- Run `git show-ref --verify refs/archive/hosted-v2-pre-core-closure` and confirm
  it resolves to the recorded commit.
- Restore that ref in a clean worktree and compare its contents with the archive
  manifest; every listed item must be present.

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
