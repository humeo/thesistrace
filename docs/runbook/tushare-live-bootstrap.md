# Tushare adapter credential verification

The development Core uses the deterministic Fixture adapter. Tushare remains a
canonical `DataSource` adapter, but it is not selected by the current product
runtime and it has no source-specific HTTP route.

To verify a real Tushare credential and the adapter's required provider
contracts without publishing a Dataset Release:

```sh
export TUSHARE_TOKEN='...'
mise exec -- pnpm check:live-tushare
```

The command performs provider preflight, deterministic collection, and
canonical normalization. A successful report has top-level `status: passed`,
lists every required provider contract with its Tushare `api_name` and status,
and includes the canonical schema, covered session range, and Research Session
count under `bootstrap_collection`.

If either phase fails, the command exits non-zero and prints a structured
report with the completed preflight evidence, failed Tushare API name, and
source error code when available.

The first-release source contract deliberately does not request Tushare's
`stock_st` API and does not exclude historical ST instruments from Research.
This limitation is explicit: a successful check does not prove ST coverage.

The token is sent only in Tushare request bodies and is not written to product
state, Publication objects, logs, or test evidence.

The private `thesistrace-data-operator-v1 bootstrap` command writes JSON Lines
progress to stderr while reserving stdout for its single final outcome. Progress
identifies collection, validation, materialization, and publication phases;
long adjustment-anchor collection reports completed listing dates and resolved
instrument counts. Tushare rate limiting is reported with the affected API,
attempt number, and next retry delay. Source tokens and response bodies are
never included.

For a bounded initial validation, pass `--start-date YYYY-MM-DD`; `--as-of`
remains the frozen end instant and determines the completed market day.

Tushare response code `40203` is treated as rate limiting and retried with
exponential backoff. The observed transient rejection `50101` is also retried
with the same bounded backoff and becomes an upstream-unavailable failure only
after attempts are exhausted. Response code `2002` remains a
missing-permission failure.
The live adapter also paces every upstream request so the documented 2000-point
access tier does not use the high-frequency request profile intended for higher
tiers.

After the calendar, instrument reference, and adjustment anchors have been
collected, the private operator atomically records a token-free checkpoint
under the mounted Canonical Data root. A later bootstrap for the exact same
request window restores that checkpoint and resumes at market facts instead of
repeating the expensive anchor collection. The checkpoint is cleared only
after a Dataset Head is successfully published; failed source collection keeps
it available for recovery.

This credential-dependent command is deliberately outside `pnpm check`. A
successful run proves adapter access and source coverage; it does not publish
through a hidden runtime or prove a production schedule.
