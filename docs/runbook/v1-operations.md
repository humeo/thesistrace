# ThesisTrace V1 operator runbook

This runbook operates one single-node, single-operator ThesisTrace Workspace.
Access control belongs to the deployment boundary. The application does not
provide users, tenants, RBAC, broker execution, intraday signals, alerts, or an
automatic market-close scheduler.

## 1. Install and start

Required tools are Python with `uv` and Bun.

```sh
uv sync
bun install --cwd web
make dev
```

Open `http://127.0.0.1:5173`. `make dev` starts the API on port 8000, the
persistent worker, and the Vite Web UI. The default durable Workspace is
`.local/`.

Use another durable directory by exporting it before starting the processes:

```sh
export THESISTRACE_HOME='/absolute/path/to/thesistrace-data'
make dev
```

The directory contains `metadata.sqlite3` and content-addressed objects. They
are one backup and recovery unit.

Verify the process boundary:

```sh
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/workspace
```

Do not operate research while `database`, `object_store`, or `worker` is
reported unavailable.

## 2. Fixture Bootstrap

The Web button **发布 Fixture Bootstrap** is the normal local and CI acceptance
entry point. The equivalent idempotent API call is:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/dataset-releases/bootstrap \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: fixture-bootstrap-v1' \
  -d '{"fixture":"v1"}'
```

The result is one immutable root Dataset Release with 756 Research Sessions.
Repeating the same idempotency key returns the same Release.

## 3. Live Tushare Bootstrap

Tushare is the sole live source. Supply its credential only as deployment
configuration:

```sh
export TUSHARE_TOKEN='...'
make dev
curl -X POST http://127.0.0.1:8000/api/v1/sources/tushare/preflight
```

After a successful preflight, follow
[Tushare live Bootstrap](./tushare-live-bootstrap.md). The token is sent only
to Tushare and is never written to metadata, logs, Dataset Releases,
Definitions, Results, or Tracking Checkpoints.

In an empty Workspace, choose the completed session in **LIVE AS OF** and click
**发布 Live Tushare Bootstrap**. The Web UI calls the same public API shown in
the live Bootstrap runbook; it never asks for or stores the token.

Automated tests prove the source contract with a recording transport. They do
not prove that a deployment token has current permissions or that Tushare is
available. A live claim therefore requires the deployment operator to run the
preflight and live Bootstrap.

## 4. Post-close publication

Publication runs only after the intended A-share session is complete. It
commits a new immutable Release first; only then does it enqueue Advances for
active DailyTracks. A Track failure cannot roll back a Release.

The deterministic acceptance path is available in the Web UI as **发布下一
Fixture Session**, or by API:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/dataset-releases/publish-fixture \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: fixture-close-2026-07-30' \
  -d '{"new_sessions":1,"corrections":[]}'
```

For missed sessions, set `new_sessions` to the real number of intervening
Research Sessions. ThesisTrace publishes one catch-up Release rather than
inventing historical daily Releases. A correction must accompany at least one
new session:

```json
{
  "new_sessions": 1,
  "corrections": [
    {
      "session": "2026-07-01",
      "instrument_id": "equity:600000.SH",
      "field": "close_raw",
      "value": "8.0500"
    }
  ]
}
```

For a Workspace rooted in a live Tushare Bootstrap, publish the real
post-close slice by choosing **LIVE AS OF** and clicking **发布 Live Tushare
Session**, or call the same API directly:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/dataset-releases/publish-live \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: live-close-2026-07-30' \
  -d '{"as_of":"2026-07-30"}'
```

This call fetches only source rows from the current Release frontier through
`as_of`; it does not rescan the three-year price history. If sessions were
missed, the same call publishes one catch-up Release. `NO_NEW_RESEARCH_SESSION`
publishes nothing. Live publication is accepted only against a live-rooted
Release; fixture and live chains cannot be mixed.

## 5. Run research

In the Web Workspace:

1. Inspect the current Release and Canonical Field Catalog.
2. Edit the Research Definition Draft.
3. Save the Draft if an editable checkpoint is useful.
4. Select **运行研究**. This atomically validates the Draft, freezes a version,
   pins the current Release, and queues one ResearchRun.
5. Wait for `SUCCEEDED`, then inspect Factor, Strategy, provenance, diagnostics,
   daily charts, and the immutable artifact downloads.

`queued` and `running` Runs can be cancelled in **运行与追踪记录**. Terminal Runs
can be rerun; rerun creates a new Run identity but preserves the frozen inputs.
Never edit SQLite status fields by hand.

## 6. Start and inspect Daily Tracking

Select **开始每日追踪** only from a successful Result Bundle. A DailyTrack fixes
its origin, Definition, numeric contract, account state, and Generation.

After each later Release, inspect:

- Head Checkpoint and target Release;
- current Generation;
- pending or blocked Advance count (`lag`);
- latest 1-day Rank IC summary;
- current simulated Net NAV;
- matured Label event count;
- Attempts and stable failure reason codes.

Select **停止追踪** to prevent future Advances. Existing Generations,
Checkpoints, account state, and evidence remain immutable and readable.

## 7. Backup

Back up metadata and objects together. Prefer stopping API and Worker briefly,
then copy the whole configured `THESISTRACE_HOME` directory with filesystem
snapshot tooling. If downtime is not possible, create a consistent SQLite
backup first and then snapshot the immutable object directory:

```sh
sqlite3 /absolute/path/to/thesistrace-data/metadata.sqlite3 \
  ".backup '/absolute/path/to/thesistrace-data/metadata.backup.sqlite3'"
```

Verify that the backup contains:

- the SQLite backup;
- `objects/sha256/`;
- `objects/manifests/`.

The Tushare token is not part of a backup and must be restored separately
through deployment configuration.

## 8. Recovery

1. Stop the failed processes without deleting the Workspace.
2. Restore `metadata.sqlite3` and the matching objects from the same backup.
3. Start API and Worker against that directory.
4. Check `/api/v1/health`, then inspect Run Attempts and Track Advances.

On startup, the worker marks stale running Attempts with
`ABANDONED_ATTEMPT` and safely retries the same durable Run or Advance
identity. A failed Result publication leaves the Run without a partial Result
Bundle. A failed Track publication leaves its prior Head unchanged.

Common stable reason codes include:

- source: `TOKEN_MISSING`, `MISSING_PERMISSION`, `UPSTREAM_UNAVAILABLE`,
  `INCOMPLETE_ADJUSTMENT_ANCHOR`, `INVALID_ADJUSTMENT_FACTOR`,
  `INCOMPLETE_REQUIRED_MARKET_FACTS`, `NO_NEW_RESEARCH_SESSION`;
- Definition: `FIELD_NOT_AUTHORABLE`, `WINDOW_OUT_OF_RANGE`,
  `HOLDINGS_COUNT_OUT_OF_RANGE`, `REBALANCE_INTERVAL_OUT_OF_RANGE`;
- execution: `TRANSIENT_FAILURE`, `CALCULATION_FAILED`,
  `TRACKING_CALCULATION_FAILED`, `TRACK_STOPPED`, `EQUIVALENCE_MISMATCH`.

Fix the diagnosed dependency or input, then use retry/rerun. Do not delete old
Releases, Result Bundles, Generations, or Checkpoints to make a retry succeed.

## 9. Verify a checkout

```sh
make check
```

This runs backend lint and tests, TypeScript checking, the production Web
build, and a real-browser fixture flow. The browser flow covers Bootstrap,
Draft, frozen Definition, ResearchRun, Factor/Strategy result, artifact
navigation, DailyTrack activation, later Release publication, Track advance,
narrow-screen reload, and stop.

Canonical Batch-Incremental Equivalence is also available for a Track:

```sh
curl -X POST \
  http://127.0.0.1:8000/api/v1/daily-tracks/TRACK_ID/verify-equivalence
```

An equivalence mismatch is a failed verification, not a warning.
