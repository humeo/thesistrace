# Financial I/O benchmark

Run the committed 2010-scale benchmark, including a real PostgreSQL-backed
Tracking Advance, with:

```sh
./scripts/test-runtime benchmark
```

That verification run writes results only to its isolated evidence directory.
To deliberately replace both the committed baseline and the repository budgets
derived from it, run:

```sh
THESISTRACE_UPDATE_BENCHMARK_BASELINE=1 ./scripts/test-runtime benchmark
```

`THESISTRACE_BENCHMARK_OUTPUT` may override the result path for an ordinary
verification run. It is rejected in baseline-update mode so the committed
baseline and its derived budgets cannot be updated separately.

The profile fixes a 2010-to-current weekday calendar, 5,541 historical ordinary
A-share identities, a dense Top300 execution slice across all 4,334 sessions
that rotates deterministically through all 5,541 historical identities, three
wide statement schemas whose retained fields are sparse but all represented,
and 34 source-version/revision rows for every instrument and endpoint. The setup
therefore writes the ordinary collector's 16,623 endpoint-instrument Raw
Financial Batches instead of substituting a small fixture.

Each scenario has five controlled `cold` samples whose addressed-file reads use
Linux `POSIX_FADV_DONTNEED` or macOS `F_NOCACHE`, and five `warm` samples after
an explicit untimed preload. Tracking samples create successful seed Runs,
activate Tracks, then measure the real claim, pin, checkpoint/cache restore,
incremental Kernel execution, and checkpoint publication path. Both phases
record nearest-rank P50/P95 duration, addressed files and bytes opened,
projected Parquet rows and columns, and Python peak memory under `tracemalloc`.

`financial-io-2010-baseline.json` is the measured evidence. Release budgets are
exact for deterministic object, byte, row, and column counts. P95 duration and
peak memory are capped at three times and two times the committed baseline,
respectively: deliberately wide enough for host variance, but finite so a
material CPU or memory regression fails. The full-scale command is part of
`pnpm check:release`, not the ordinary development test loop. It fails before
writing results when any budget or the price-only/descriptor zero-financial-I/O
invariant regresses.
