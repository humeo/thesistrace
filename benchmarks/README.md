# Benchmarks

## Long Research qualification

Run the release-blocking final Production Image qualification with:

```sh
pnpm test:benchmark
```

The command builds the final image once and measures Factor Evaluation and
Strategy Backtest separately against the same frozen 2010-to-latest Top 3000
Generation. Each kind runs five cold and five warm fresh ResearchRuns in an
isolated Product State, with one 2-vCPU/2-GiB Research Worker slot, a 1.5-GiB
execution budget, and two calculation threads. Warm preload reads Canonical
objects only; every measured sample begins after an ordinary Product State
reset and proves the PostgreSQL and RustFS Product State is empty.

The structured report is saved below the run's `.local/test-runs/<run-id>/`
evidence directory. It records deterministic nearest-rank duration P95,
per-phase timings, peak RSS, first durable Checkpoint, confirmed cancellation,
child exit, exact Result object sets, and cross-kind Factor Summary identity.
Duration and first-Checkpoint latency use an independent PostgreSQL observer's
monotonic clock, starting when the committed running Attempt becomes visible
and ending only when the committed Checkpoint or terminal state becomes visible
to that connection. Transaction-start timestamps are diagnostic fields, not
gate timers.
Factor Evaluation fails if any Strategy phase, continuation, observation
partition, or Result object appears. A failed sample fails the run; it is never
replaced by a retry.

## Financial I/O benchmark

Run the deterministic market/financial I/O benchmark directly with:

```sh
uv run python scripts/benchmark_financial_io.py
```

Use `--output <path>` for an explicit result artifact. Updating repository
budgets is a deliberate two-step operation using `--skip-budgets
--update-budgets`; ordinary verification never mutates committed evidence.

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
