# Tushare live Bootstrap

Live publication is optional at development time and credential-dependent. A
fixture acceptance result is never evidence that the deployment's Tushare
token has the required permissions or coverage.

## Configure

Provide the token only through deployment configuration:

```sh
export TUSHARE_TOKEN='...'
make dev
```

The token is passed only in Tushare HTTP request bodies. ThesisTrace does not
write it to metadata, logs, source evidence, Dataset Release manifests, or
Result Bundles.

## Preflight

Before a live Bootstrap, call:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/sources/tushare/preflight
```

The preflight checks the V1 source contracts for stock reference, the SSE and
SZSE calendars, daily price, adjustment factor, suspension, historical ST,
daily price limits, and SW2021 classification/membership. A missing permission
returns a reason-coded `424` response and publishes nothing.

The underlying HTTP request follows Tushare's documented `api_name`, `token`,
`params`, and `fields` envelope. See the
[Tushare HTTP API](https://tushare.pro/document/1?doc_id=130), together with the
[trade calendar](https://tushare.pro/document/2?doc_id=26),
[adjustment factor](https://tushare.pro/document/2?doc_id=28),
[historical ST](https://tushare.pro/document/2?doc_id=397), and
[daily price limit](https://tushare.pro/document/2?doc_id=183) contracts.

## Publish

After the market session is complete:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/dataset-releases/bootstrap-live \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: live-bootstrap-2026-07-29' \
  -d '{"as_of":"2026-07-29"}'
```

ThesisTrace preflights permissions, fetches deterministic paginated source
responses, retains them, validates exactly 756 common Research Sessions,
normalizes the Canonical EOD contract, writes content-addressed objects, and
commits the root Release last. Any upstream, coverage, schema, or validation
failure leaves the latest Release unchanged.

## Acceptance boundary

Automated tests use a recording transport and generated source snapshot to
prove pagination, reason-coded failures, secret exclusion, canonical
normalization, and the shared atomic publication boundary. They do not make a
live network request. A deployment operator must run the preflight and live
Bootstrap with that deployment's own token before claiming live acceptance.

