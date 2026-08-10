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

This credential-dependent command is deliberately outside `pnpm check`. A
successful run proves adapter access and source coverage; it does not publish
through a hidden runtime or prove a production schedule.
