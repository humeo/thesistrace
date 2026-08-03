# 14 — Migrate Tushare to the canonical DataSource

**What to build:** Make Tushare a provider adapter of the same canonical Data
contract as Fixture without creating a second product or publication path.

**Blocked by:** 10.

**Status:** ready-for-agent

- [ ] Tushare and Fixture return the same canonical source-batch shapes and
  provider-independent error categories.
- [ ] Tushare owns only provider protocol, paging, throttling, and mapping;
  Data retains coverage, schema, point-in-time, calendar, and publication rules.
- [ ] Tushare knows no Dataset Release ID, PostgreSQL, S3, ResearchRun, or
  DailyTrack.
- [ ] Product requests and responses expose no `live`, `fixture`, `bootstrap`,
  or `increment` mode.
- [ ] Offline adapter evidence uses no credentials or network claims.
- [ ] A separate live Tushare gate exists, but its real execution does not block
  the default Core gate or Core closure.

**How to verify:**

- Run `uv run pytest -q tests/adapters` with offline Fixture and recorded
  provider-boundary cases; confirm both adapters satisfy one contract.
- When valid credentials are intentionally available, run
  `make check-live-tushare`; record that result separately and do not treat its
  absence as failure of this ticket.

## Comments
