---
status: accepted
---

# Paginate the ordinary balance sheet inside one logical shard

The ordinary Tushare financial source keeps one resumable Data checkpoint for
each `endpoint × instrument`. The `balancesheet` adapter obtains that logical
complete-history response with fixed `limit=100` and increasing `offset`
requests, preserves page order and duplicate rows, requires one stable field
sequence across every page, and stops only on a page shorter than 100 rows.
Repeated full pages, an oversized page, schema drift, or more than 100 pages
fail closed. The 2026-08-14 live capability check for `000001.SZ` returned 100
rows at offset 0 and 62 rows at offset 100, matching the 162-row annual-shard
comparison.

`income` and `cashflow` remain one physical ordinary-interface request per
logical shard while the capability comparison proves those responses complete.
The collection contract accepts only the single `complete-history` logical
shard. It does not expose an executable date-shard alternative, dynamically
change request shapes, deduplicate provider rows, or turn provider pages into
independent publication checkpoints. Raw Financial Batches identify this
behavior as `tushare-financial-ordinary-v2`.
