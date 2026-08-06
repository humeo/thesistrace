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
canonical normalization. It prints only the canonical schema, covered session
range, and Research Session count. The token is sent only in Tushare request
bodies and is not written to product state, Publication objects, logs, or test
evidence.

This credential-dependent command is deliberately outside `pnpm check`. A
successful run proves adapter access and source coverage; it does not publish
through a hidden runtime or prove a production schedule.
