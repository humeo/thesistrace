# Private Data Operator

The Data Operator is a deployment-private command. It is not an HTTP route or
a Web capability, and normal API/Worker startup never runs it.

Bootstrap is explicit and only establishes the first Head of an empty mounted
Canonical Data Store. Freeze a timezone-aware operator instant and supply an
idempotency key:

```sh
docker compose -f deploy/core/compose.yaml run --rm \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator bootstrap \
  --idempotency-key bootstrap-2026-08-09 \
  --start-date 2026-07-09 \
  --as-of 2026-08-09T18:00:00+08:00
```

Use `--start-date YYYY-MM-DD` to bound the initial collection window. If it is
omitted, the window begins one natural year before the Shanghai calendar date
at `--as-of`. The start date must not be later than the completed market day.
Calendar collection stops at the frozen completion cutoff derived from
`--as-of`; market facts stop at the latest Research Session jointly open on SSE
and SZSE. This window is an operator convenience, not a Research Period,
Warm-up, or minimum-session rule.

For deterministic development or incident reproduction, pass a bounded
version-2 Tushare replay instead of a token:

```sh
thesistrace-data-operator bootstrap \
  --idempotency-key bootstrap-replay-1 \
  --as-of 2026-08-09T18:00:00+08:00 \
  --replay /private/operator/tushare-bootstrap-replay.json
```

Bootstrap records internal preparation time in the Head but does not set a
successful Refresh timestamp. Repeating the same key and request returns the
same outcome. A different key cannot overwrite an existing Head.

Market bootstrap and refresh use the `tushare-market-v1` source contract and
never call `index_classify` or `index_member_all`. A fresh bootstrap therefore
publishes the required Core Market Families without an Industry Family. When a
current Head already references `equity.industry_membership`, Market refresh
reuses that exact immutable Family manifest and its existing Coverage while
advancing only Market Coverage.

Live bootstrap persists a bounded, token-free checkpoint containing the
calendars and instrument reference before starting market-fact collection.
After all four market-fact endpoints succeed for one Research Session, that
session is stored as immutable SHA-256-addressed content and added atomically
to the checkpoint. If a later provider call fails, rerun the same request
window with a new idempotency key; the operator restores completed sessions
and queries only unfinished dates. `collection_progress.source` distinguishes
`checkpoint` from `upstream`. Changing the request window or source contract
fails closed instead of reusing the checkpoint. Successful publication clears
the manifest and its session content.

## Refresh and collection

Refresh is a private two-step operation. Submission records the frozen request;
work execution later claims the next request and collects from Tushare:

```sh
docker compose -f deploy/core/compose.yaml run --rm api \
  thesistrace-data-operator refresh \
  --idempotency-key refresh-2026-08-12 \
  --as-of 2026-08-12T18:00:00+08:00

docker compose -f deploy/core/compose.yaml run --rm \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator work-refresh
```

Use `work-refresh --replay /private/operator/replay.json` for deterministic
reproduction. Inspect an operation without changing it:

```sh
thesistrace-data-operator inspect-refresh \
  --idempotency-key refresh-2026-08-12
```

Garbage collection is explicit and idempotent:

```sh
thesistrace-data-operator collect \
  --idempotency-key collect-2026-08-12
```

Collection retains the current Head, live candidates, and active execution
pins. It does not make completed ResearchRuns depend on permanently retained
market-data Generations.

## Industry refresh

Industry uses the independent `tushare-industry-v1` contract. The operation
requests `index_classify` and the complete `index_member_all` history, retaining
the source `is_new`, `in_date`, `out_date`, and L1/L2/L3 values as immutable
SHA-256-addressed lineage. It does not run as part of Market bootstrap or
Market refresh:

```sh
docker compose -f deploy/core/compose.yaml run --rm \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator refresh-industry \
  --idempotency-key industry-2026-08-14 \
  --observation-through-session 2026-08-14

thesistrace-data-operator inspect-industry-refresh \
  --idempotency-key industry-2026-08-14
```

The requested observation-through date must be a Research Session in the
current Market Coverage. A successful operation replaces only the immutable
`equity.industry_membership` Family and composes it with the latest Market and
Financial Families before the one Dataset Head CAS. A concurrent Market or
Financial publication is therefore preserved. If another Industry publication
has replaced the source Family, the operation fails with
`INDUSTRY_TARGET_CHANGED`.

`(SW2021, instrument, session)` remains a single-valued primary
classification. Overlapping source intervals fail the Industry operation with
`OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION`, retain bounded diagnostics and
source lineage, and do not create a candidate or move Dataset Head. There is no
automatic interval closing, winning-row selection, `UNKNOWN`, override, or
fallback. `--replay` is an explicit deterministic test input only.

Financial collection and refresh require the live capability report and token
in deployment. Deterministic acceptance may replace only the remote transport
with the versioned product replay while exercising the same collection,
candidate, publication, and Head compare-and-swap path.

For the local Development stack, generate the live report with the same
Compose project that owns the mounted Canonical Data Store. The 74 shell-array
items below are 37 `--comparison-shard` option/value pairs, not 74 shards.
Run `pnpm dev:up` first after source changes so the one-off container uses the
current backend image:

```zsh
mkdir -p .local/operator
export THESISTRACE_TUSHARE_TOKEN="$TUSHARE_TOKEN"

tt_compose=(
  docker compose
  --project-name thesistrace-dev
  --env-file deploy/core/dev.env
  --file deploy/core/compose.yaml
  --file deploy/core/compose.dev.yaml
)

financial_probe_args=()
current_year=$(date +%Y)
for ((year = 1990; year <= current_year; year++)); do
  financial_probe_args+=(
    --comparison-shard "$year:${year}0101:${year}1231"
  )
done

"${tt_compose[@]}" run --rm --no-deps -T \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator probe-financial \
  --reference-instrument 000001.SZ \
  "${financial_probe_args[@]}" \
  > .local/operator/financial-capability.next.json

jq -e '
  .endpoints | length == 3 and
  all(.[]; .permission == "available" and .full_history_proven == true)
' .local/operator/financial-capability.next.json \
  && mv .local/operator/financial-capability.next.json \
    .local/operator/financial-capability.json
```

The probe makes one complete-history request plus one request per comparison
year for each of the three endpoints; `balancesheet` can add internal pages.
It is a bounded, one-instrument capability check, not a full-market download.
`--no-deps` is intentional: the probe requires neither PostgreSQL nor RustFS.

The host report is not part of the Compose image or named data volume. Mount
the operator directory explicitly when a container consumes it:

The first financial-capable Generation requires Market Coverage containing the
first Research Session of 2010, even when the intended Research Period starts
later. Finish that market bootstrap first and set `GENERATION` to its
`generation_manifest_sha256`; otherwise candidate materialization fails closed
with `FINANCIAL_COVERAGE_START_UNAVAILABLE` after collection.

```sh
"${tt_compose[@]}" run --rm -T \
  --volume "$PWD/.local/operator:/private/operator:ro" \
  -e THESISTRACE_TUSHARE_TOKEN \
  api thesistrace-data-operator refresh-financial \
  --idempotency-key financial-live-20260701-v2 \
  --generation-manifest-sha256 "$GENERATION" \
  --observation-through-session 2026-07-01 \
  --capability-report /private/operator/financial-capability.json
```

Add `--replay /private/operator/tushare-financial-product-replay.json` only for
an explicitly mounted deterministic replay; it is not used for live collection.

Omit `--prior-candidate-manifest-sha256` only for the first Financial Refresh
of a market-only Head. Every later refresh supplies the current financial
candidate so accepted historical versions are retained when the source no
longer returns them.

Replay is an explicit test/incident-reproduction input, never an automatic
fallback from a failed live provider.

The ordinary-interface contract has one complete-history logical shard per
`endpoint × instrument`. `balancesheet` is transparently collected with fixed
100-row `limit`/`offset` pages; `income` and `cashflow` remain single physical
requests while the capability report proves them complete. There is no
`--date-shard` collection option. Regenerate the capability report after a
source-contract change; an older report that does not prove complete history is
rejected before any full-market collection begins.

The narrow Production Image smoke builds the backend image, runs the versioned
operator twice through the shared named mount, and then starts and restarts the
API and Worker without source credentials:

```sh
./scripts/smoke-data-operator-image
```
