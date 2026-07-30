# ResearchRun storage-budget prototype

This is a throwaway prototype, not the production storage implementation.

It answers two questions:

1. Can a conservative V1 Run stay below 1 MiB after Alpha, Forward Labels,
   Factor Daily, and raw execution events are discarded?
2. Can the retained Factor summaries and Strategy metrics still be reproduced
   from the proposed minimal result boundary?

Run both validations with one command:

```bash
uv run --with 'pyarrow==25.0.0' python prototypes/run-storage-budget/validate.py
```

The size model uses 756 Strategy sessions, daily rebalancing, 100 terminal
positions, and both realistic and deliberately high-entropy data. It also
compares one-file-per-table, yearly, monthly, and daily Parquet partitioning.

Accounting values use deliberately high-entropy ADR-0109 canonical decimal
strings. This validates storage headroom, not the final production Parquet
writer contract.

## Verdict

The current deterministic Fixture stores 19,486,415 bytes across its seven
result objects. Projecting it to the proposed minimal boundary in uncompressed
canonical JSON takes 146,475 bytes, while reconstructing the current Factor
summary and complete Strategy metrics exactly.

The conservative 756-session, daily-rebalance, 100-position Parquet model takes:

| Scenario | Bytes |
| --- | ---: |
| One ZSTD Parquet file per bounded table | 176,000 |
| One ZSTD Parquet file per session | 7,044,738 |

One Parquet file per bounded Run table is part of the result: splitting the
same high-entropy data into one file per session fails the 1 MiB budget.
Canonical Dataset daily
partitioning must therefore not be copied into ResearchRun result storage.
