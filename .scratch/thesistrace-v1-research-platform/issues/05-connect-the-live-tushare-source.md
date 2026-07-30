# 05 — Connect the live Tushare source

**What to build:** Let a configured deployment preflight and bootstrap the V1
data contracts from the sole live Tushare source while preserving the same
publication behavior proven by fixtures.

**Blocked by:** 04 — Publish Calendar, Universe, Industry, and Field Catalog.

**Status:** ready-for-agent

- [ ] Credentials are read only from deployment configuration and never enter logs, Definitions, manifests, or artifacts.
- [ ] Requests implement deterministic pagination, throttling, retries, and stable source-contract versions.
- [ ] Accepted responses are retained before Canonical translation.
- [ ] Required reference, calendar, daily, adjustment, suspension, ST, price-limit, and SW2021 permissions are checked before live Bootstrap.
- [ ] Missing permissions, invalid coverage, and upstream failures produce safe reason-coded diagnostics and no partial Release.
- [ ] Contract tests prove fixture and live adapters feed the same publication boundary.
- [ ] Live acceptance is documented as credential-dependent and is never claimed from fixture evidence.
