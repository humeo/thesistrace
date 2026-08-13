# 09 — Lock 2010-scale I/O, Pin, and GC boundaries

**What to build:** Prove and enforce that the completed market-financial
execution path remains selective and safe at representative 2010-scale data.
Metadata inspection must stay cheap, market-only work must not pay the financial
I/O cost, mixed work must remain projection-bounded, and immutable objects must
survive exactly as long as active Generations and Attempts require them.

**Blocked by:** 05 — Rebuild a complete Financial Refresh candidate; 08 —
Advance, block, and resume financial DailyTracks.

**Status:** complete

- [x] A committed deterministic benchmark represents the 2010-to-current
  market and financial shape with a full ordinary A-share universe and wide
  statement columns.
- [x] Descriptor inspection, Claim, Pin, admission, and Data Overview open no
  Parquet object.
- [x] A price-only Formula reads zero financial Raw Financial Batches,
  statement objects, or financial partitions.
- [x] A financial-only or mixed Formula reads only referenced families,
  projected fields, relevant session partitions, and selected instruments.
- [x] ResearchRun and DailyTrack perform no instrument-by-session-by-field
  Python scan and no one-file-per-instrument read pattern.
- [x] Cold and warm benchmarks record P50 and P95 duration, objects opened,
  bytes read, rows scanned, and peak memory for descriptor, price-only,
  financial-only, mixed, and Tracking Advance cases.
- [x] Repository-owned budgets are derived from the representative benchmark
  and fail on a material regression without arbitrary sleep or public network.
- [x] An Attempt pinned to Generation A completes unchanged while a Financial
  or Market Refresh publishes Generation B.
- [x] Published Heads, retained Generation ownership, ResearchRun Attempts, and
  Tracking Advance Attempts protect every referenced family Manifest, Raw
  Financial Batch, and Physical Data Object from collection.
- [x] Objects with no remaining durable Generation or execution reference
  become collectible and are removed without affecting surviving results.
- [x] Identical full Financial Refresh candidates demonstrate bounded object
  growth through content reuse.
- [x] Corrupt or missing referenced objects fail closed with actionable
  diagnostics instead of being silently re-fetched or replaced.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- Passing these budgets is a prerequisite for publishing the first real
  financial-capable Head.
