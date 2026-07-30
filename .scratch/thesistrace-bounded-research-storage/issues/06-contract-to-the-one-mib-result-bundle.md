# 06 — Contract to the one-MiB Result Bundle

**What to build:** Make the compact Result Bundle the sole durable
ResearchRun result, remove the migration-only intermediate objects, and reject
any Run that cannot publish every required conclusion within one exact MiB.

**Blocked by:** 03 — Add the compact Result Bundle projection; 05 — Advance DailyTrack from the bounded Working Cache.

**Status:** resolved

- [x] New Result Manifests, Activation Checkpoints, and Tracking Checkpoints contain no Alpha Matrix, stock-level Forward Return Label, daily Factor observation or curve, target history, raw order, Child Order, fill, rejection-event detail, or growing diagnostic object.
- [x] The exact bytes of every ResearchRun-owned manifest and payload total no more than `1,048,576`, and the published manifest exposes the independently verifiable logical total.
- [x] Shared Dataset Release objects are excluded from the Run budget, while content-addressed deduplication never reduces the logical bytes charged to an individual Run.
- [x] A valid but oversized complete result fails publication without a succeeded ResearchRun, Result Bundle identifier, Result Manifest, or product-visible partial report.
- [x] Cancellation or a stale Attempt cannot publish a prepared compact bundle after losing ownership of the ResearchRun.
- [x] The production writer capacity gate retains 756 Strategy sessions, daily Rebalance and execution aggregates, and up to 3,000 Terminal Positions below the one-MiB limit.
- [x] Factor summaries and all confirmed Strategy reports remain exactly reconstructible after every legacy compatibility object and reader has been removed.
- [x] Development fixture artifacts may be rebuilt under the compact contract, and no production migration subsystem or general raw-artifact download product is introduced.

## Comments

- ResearchRun publication now writes only the eight compact Result objects.
  Alpha, stock-level Labels, daily Factor history, raw Strategy history, and
  their compatibility indexes and readers have been removed from Result,
  Activation, normal Advance, historical-correction replay, and runtime replay
  contracts.
- Each manifest publishes exact `logical_bytes` for payloads, manifest, total,
  and the `1,048,576`-byte limit. Payload bytes are summed per logical Result
  reference, so shared Dataset Release objects are excluded and object
  deduplication cannot lower the charge.
- The byte gate runs before the Result Manifest is published or the
  ResearchRun succeeds. A 50,000-position valid calculation fixture proves an
  oversized result fails with no Bundle identifier, manifest pointer, or named
  Result Manifest.
- Result payloads may be prepared before the final ownership fence, but the
  named Result Manifest is published only after the running Attempt wins the
  atomic success transition. A cancellation test proves a prepared compact
  bundle cannot become product-visible after ownership is lost.
- Production Parquet capacity acceptance writes 756 Strategy Daily rows, 756
  Rebalance rows, 756 execution rows, and 3,000 Terminal Positions and verifies
  their logical Result total remains below one MiB.
- Full Factor summaries and every confirmed Strategy report metric are compared
  exactly with transient calculation outputs after compatibility objects are
  absent.
- Verification: full backend suite `57 passed`; focused Result, activation,
  capacity, oversize, and cancellation acceptance `7 passed`; full compact
  replay/Daily Tracking acceptance `1 passed`; `uv run ruff check src tests`;
  `bun run typecheck`; and `bun run build`.
