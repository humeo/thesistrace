# 14 — Migrate Tushare to the canonical DataSource

**What to build:** Make Tushare a provider adapter of the same canonical Data
contract as Fixture without creating a second product or publication path.

**Blocked by:** 10.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Tushare and Fixture return the same canonical source-batch shapes and
  provider-independent error categories.
- [x] Tushare owns only provider protocol, paging, throttling, and mapping;
  Data retains coverage, schema, point-in-time, calendar, and publication rules.
- [x] Tushare knows no Dataset Release ID, PostgreSQL, S3, ResearchRun, or
  DailyTrack.
- [x] Product requests and responses expose no `live`, `fixture`, `bootstrap`,
  or `increment` mode.
- [x] Offline adapter evidence uses no credentials or network claims.
- [x] A separate live Tushare gate exists, but its real execution does not block
  the default Core gate or Core closure.

**How to verify:**

Required offline gate (uses no credentials or network):

```sh
set -eu
uv run pytest -q tests/adapters
```

Optional live-provider gate (run only when valid credentials are intentionally
available; not running it is not a ticket failure):

```sh
make check-live-tushare
```

## Comments

- `TushareDataSource` now implements the same `collect(CollectionPlan) ->
  CanonicalSourceBatch` boundary as Fixture. Increment plans carry the previous
  canonical payload, so Tushare receives no Dataset Release ID or storage
  dependency.
- Data owns the shared error categories, exchange-calendar intersection,
  fixed 756-session Bootstrap window, canonical field catalog, liquidity
  mapping, and source-correctable Price-field allowlist. Tushare retains its
  HTTP protocol, paging, retry/throttling, provider response mapping, and
  provider-specific diagnostic codes behind the adapter.
- Provider responses missing requested fields and malformed recorded snapshots
  fail through provider-independent DataSource errors. Increment materialization
  applies corrections only to the seven allowed source Price fields; provider
  private, derived, and identity fields are rejected.
- The required offline command passed `37 passed` without credentials or
  network. Legacy Tushare, Dataset, and incremental correction regressions also
  passed, as did the real PostgreSQL/RustFS Fixture publication, later-update,
  and recovery regression.
- `make check-live-tushare` is a separate opt-in gate. It preflights credentials,
  collects through the canonical Tushare adapter, and prints only canonical
  schema, covered range, and Research Session count. It was not executed because
  valid live credentials were not intentionally supplied; no live availability,
  freshness, or publication claim is made.
- Initial independent review found four blocking boundary defects: untyped
  correction application, malformed payload errors leaking through, calendar
  and coverage rules remaining in the provider collector, and provider details
  in live-gate output. Re-review then found an unbounded correction field. All
  five were closed with regression tests. Final independent review passed
  `Standards: PASS` and `Spec: PASS` with no findings.
- The first repository gate exposed an existing Web startup race: a temporary
  `/api/v1/session` proxy failure was permanently interpreted as Hosted login
  while the second Playwright server restarted. Auth-mode detection now chooses
  V1 only on `404`, login only on `401/403`, and retries transient/network
  responses with cleanup on unmount. Independent re-review kept both axes at
  PASS. The final single `make check` invocation exited `0`: Ruff passed,
  Python passed `518 passed, 50 skipped, 2 warnings`, Web typecheck/build passed,
  and narrow/desktop Playwright passed in `31.7s` and `30.7s`.
