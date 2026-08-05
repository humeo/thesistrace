# 49 — Prove Core closure from clean state

**What to build:** Run one deterministic proof of the complete Core product
loop after every product boundary and contraction is already independently
accepted.

**Blocked by:** 48.

**Status:** ready-for-agent

- [ ] The default gate starts or addresses isolated real PostgreSQL and pinned
  RustFS from clean schemas and an empty bucket.
- [ ] The visible flow publishes Fixture Data, saves a nameless incomplete
  Definition, rejects an invalid Run without creating one, then executes a
  corrected Run and shows its bounded Factor plus Strategy/Benchmark Result.
- [ ] Editing and running again creates an independent Run; Rerun creates a new
  ID with the original immutable input and Release.
- [ ] Cancel proves that a late worker result cannot become visible.
- [ ] A succeeded Run starts at most one DailyTrack; a later Release advances it
  in order; failure blocks it without moving Head; Retry recovers the same
  target; Stop is irreversible.
- [ ] Restarting HTTP and worker processes preserves all four resources,
  receipts, lifecycle state, and authoritative publications.
- [ ] No Hosted, login, deployment, SQLite, fake S3, old runtime fallback, or
  live Tushare path participates.
- [ ] A newly discovered independent defect becomes a blocking bug ticket; this
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
