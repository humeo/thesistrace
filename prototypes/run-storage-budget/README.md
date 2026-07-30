# ResearchRun and Daily Tracking storage-budget prototype

This is a throwaway prototype, not the production storage implementation.

It answers three questions:

1. Can a conservative V1 Run stay below 1 MiB after Alpha, Forward Labels,
   Factor Daily, and raw execution events are discarded?
2. Can the retained Factor summaries and Strategy metrics still be reproduced
   from the proposed minimal result boundary?
3. Can Daily Tracking advance incrementally with a bounded, rebuildable cache
   instead of recomputing all historical Alpha and Factor observations?

Run both validations with one command:

```bash
uv run --with 'pyarrow==25.0.0' python prototypes/run-storage-budget/validate.py
```

The ResearchRun size model deliberately stress-tests 756 retained Strategy
sessions—more than V1's 504-session report window—plus daily rebalancing, up to
3,000 actual or terminal positions, and deliberately high-entropy data. It
compares one Parquet file per bounded table with one Parquet file per session.

The separate Daily Tracking cache model uses Top3000 and contains only:

- one ZSTD Parquet final-Alpha partition for each of at most 21 signal sessions
  waiting for the longest 20-session Forward Return Label;
- 504 signal sessions × the 1/5/20-session horizons of daily Factor
  aggregates in one compact ZSTD Parquet file;
- a small cache-basis record that makes the cache disposable when its
  Checkpoint or definition no longer matches.

This cache is built once from the seed Dataset Release only after a successful
ResearchRun explicitly seeds a DailyTrack. ResearchRuns that never enable
Tracking do not prebuild or retain it.

The maximum 252-session Alpha lookback is a computation semantic. Those 252
input sessions remain in the Dataset Release and are not copied into the
Daily Tracking cache. Stock-level Labels and Factor daily curves are not
persisted in the immutable ResearchRun result.

ResearchRun accounting values use deliberately high-entropy ADR-0109 canonical
decimal strings. Pending Alpha and Factor observations use high-entropy IEEE
754 binary64 values, matching their ADR-0109 numeric representation. This
validates storage headroom, not the final production Parquet writer contract.

## Verdict

The current deterministic Fixture stores 19,486,415 bytes across its seven
result objects. Projecting it to the proposed minimal boundary in uncompressed
canonical JSON takes 146,475 bytes, while reconstructing the current Factor
summary and complete Strategy metrics exactly.

The conservative 756-session, daily-rebalance, 3,000-terminal-position
ResearchRun model takes:

| Scenario | Bytes |
| --- | ---: |
| One ZSTD Parquet file per bounded table | 335,168 |
| One ZSTD Parquet file per session | 7,195,884 |

One Parquet file per bounded Run table is part of the result: splitting the
same high-entropy data into one file per session fails the 1 MiB budget.
Canonical Dataset daily
partitioning must therefore not be copied into ResearchRun result storage.

The conservative Top3000 Daily Tracking cache takes:

| Cache object | Rows | Bytes |
| --- | ---: | ---: |
| Pending final Alpha: 21 × 3,000 in 21 partitions | 63,000 | 1,156,805 |
| Rolling Factor aggregates: 504 × 3 | 1,512 | 120,417 |
| Cache basis with payload checksums | — | 3,784 |
| **Total: 22 Parquet + 1 JSON files** | **64,512** | **1,281,006** |

The measured cache is not part of the ResearchRun contract: the immutable
ResearchRun still has the hard 1 MiB limit, while this cache is
non-authoritative, rebuildable, present only for an enabled DailyTrack, and
bounded independently of how many years the Track runs. V1 has not assigned a
separate hard byte budget to the cache.

The per-signal-session layout deliberately trades about 514 KiB of additional
bounded resident storage for lower normal-update write amplification. A
Top3000 Advance writes at most one approximately 55 KiB Pending Alpha
partition, the approximately 120 KiB Rolling Factor file, and the approximately
4 KiB basis record: 179,310 bytes in this stress model. It then evicts one
matured partition instead of rewriting all 63,000 pending Alpha rows.
