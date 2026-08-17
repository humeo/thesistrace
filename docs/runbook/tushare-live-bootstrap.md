# Tushare adapter credential verification

The development Core uses the deterministic Fixture adapter. Tushare remains a
canonical `DataSource` adapter, but it is not selected by the current product
runtime and it has no source-specific HTTP route.

To verify a real Tushare credential and the adapter's required provider
contracts without moving the Dataset Head:

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

The private `thesistrace-data-operator bootstrap` command writes JSON Lines
progress to stderr while reserving stdout for its single final outcome. Progress
identifies calendar, instrument-reference, market-fact, validation,
materialization, and publication phases. Tushare rate limiting is reported with
the affected API, attempt number, and next retry delay. Source tokens and
response bodies are never included.

For a bounded initial validation, pass `--start-date YYYY-MM-DD`; `--as-of`
remains the frozen end instant and determines the completed market day.

Full-market daily bars, adjustment factors, suspensions, and price limits are
collected one shared SSE/SZSE Research Session at a time with `trade_date`.
This follows the provider's documented full-market request pattern and avoids
asking one response to contain multiple sessions for every listed instrument.
Each completed session emits `collection_progress` with `completed_sessions`,
`total_sessions`, and `source`; bootstrap and incremental refresh use the same
collection path, while only bootstrap enables the private recovery checkpoint.
Suspension collection requests only Tushare `suspend_type=S`; a null
`suspend_timing` on such a row is the provider's full-session form, while
resume rows are not suspension evidence. Intraday ranges accept Tushare's
one- or two-digit hour spelling, so both `9:31-9:41` and `09:31-09:41` map to
an after-open suspension. For `suspend_type=S`, the provider's
`09:30-09:30` sentinel is a full-session suspension; a same-session daily bar
would make that evidence contradictory and fail closed. Because `suspend_d`
reports stop/resume events rather than repeating the state every day, a
confirmed full-session suspension carries across later sessions with no daily
bar until a daily bar resumes. An isolated absence without that predecessor
state still fails closed.

Tushare response code `40203` is treated as rate limiting and retried with
exponential backoff. The observed transient rejection `50101` is also retried
with the same bounded backoff and becomes an upstream-unavailable failure only
after attempts are exhausted. Response code `2002` remains a
missing-permission failure.
The live adapter also paces every upstream request so the documented 2000-point
access tier does not use the high-frequency request profile intended for higher
tiers.

After the calendar and instrument reference have been collected, the private
operator atomically records the single current token-free checkpoint under the
mounted Canonical Data root. Each session is added only after daily bars,
adjustment factors, suspensions, and price limits have all succeeded; its raw
payload is immutable SHA-256-addressed content. A later bootstrap for the exact
same request window and source contract restores every completed session and
queries only the unfinished dates. The checkpoint is cleared only after a
Dataset Head is successfully published; failed source collection keeps it
available for recovery. Invalid, corrupt, or differently scoped checkpoints
fail closed.

This credential-dependent command is deliberately outside `pnpm check`. A
successful run proves adapter access and source coverage; it does not publish
through a hidden runtime or prove a production schedule.
