# 49 — Prove Core closure from clean state

**What to build:** Run one deterministic proof of the complete Core product
loop after every product boundary and contraction is already independently
accepted.

**Blocked by:** 48, 50.

**Status:** complete

- [x] The default gate starts or addresses isolated real PostgreSQL and pinned
  RustFS from clean schemas and an empty bucket.
- [x] The visible flow publishes Fixture Data, saves a nameless incomplete
  Definition, rejects an invalid Run without creating one, then executes a
  corrected Run and shows its bounded Factor plus Strategy/Benchmark Result.
- [x] Editing and running again creates an independent Run; Rerun creates a new
  ID with the original immutable input and Release.
- [x] Cancel proves that a late worker result cannot become visible.
- [x] A succeeded Run starts at most one DailyTrack; a later Release advances it
  in order; failure blocks it without moving Head; Retry recovers the same
  target; Stop is irreversible.
- [x] Restarting HTTP and worker processes preserves all four resources,
  receipts, lifecycle state, and authoritative publications.
- [x] No Hosted, login, deployment, SQLite, fake S3, old runtime fallback, or
  live Tushare path participates.
- [x] A newly discovered independent defect becomes a blocking bug ticket; this
  final ticket does not absorb first-time feature implementation or debugging.

**How to verify:**

```sh
set -eu

./scripts/core-test-runtime down
make check

if make -n check | rg 'check-live-tushare|check_live_tushare'; then
  echo 'The optional live Tushare gate leaked into the Core closure gate' >&2
  exit 1
fi

make -n check-live-tushare | rg 'scripts/check_live_tushare\.py'
```

## Comments

- The first clean proof exposed repeated transient `IncompleteRead` failures
  from RustFS while reading the same approximately 19.7 MiB content-addressed
  object. The defect became blocking Bug Ticket 50; its bounded standard-S3
  response-body retry was implemented in `81cb836`, independently reviewed
  Standards PASS / Spec PASS, verified, and closed in `42350fe` before this
  ticket resumed.
- Final exact `make check` from a stopped runtime passed: Ruff; Kernel,
  Architecture, and Adapter `141 passed` in `133.98s`; Web typecheck and
  production build; clean PostgreSQL/RustFS Integration/Acceptance `101 passed`
  in `725.73s` with one dependency deprecation warning; a second clean reset
  followed by Web E2E `18 passed` in `1.3m`; final runtime cleanup succeeded.
- The E2E proof covers the four-resource shell, first Fixture Release, nameless
  incomplete Definition, rejected and corrected Run, bounded Result, Cancel,
  immutable-input Rerun with a new ID, DailyTrack admission, analysis, isolated
  failure, same-target Retry, irreversible Stop, and stable resource URLs.
- `make -n check` contains neither `check-live-tushare` nor
  `check_live_tushare`; `make -n check-live-tushare` resolves separately to
  `uv run python scripts/check_live_tushare.py`. No live credential or Hosted
  path participated in the Core proof.
