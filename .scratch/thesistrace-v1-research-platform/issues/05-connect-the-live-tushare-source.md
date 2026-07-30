# 05 — Connect the live Tushare source

**What to build:** Let a configured deployment preflight and bootstrap the V1
data contracts from the sole live Tushare source while preserving the same
publication behavior proven by fixtures.

**Blocked by:** 04 — Publish Calendar, Universe, Industry, and Field Catalog.

**Status:** resolved

- [x] Credentials are read only from deployment configuration and never enter logs, Definitions, manifests, or artifacts.
- [x] Requests implement deterministic pagination, throttling, retries, and stable source-contract versions.
- [x] Accepted responses are retained before Canonical translation.
- [x] Required reference, calendar, daily, adjustment, suspension, ST, price-limit, and SW2021 permissions are checked before live Bootstrap.
- [x] Missing permissions, invalid coverage, and upstream failures produce safe reason-coded diagnostics and no partial Release.
- [x] Contract tests prove fixture and live adapters feed the same publication boundary.
- [x] Live acceptance is documented as credential-dependent and is never claimed from fixture evidence.

## Comments

- Added environment-only credential loading, permission preflight, deterministic
  pagination/throttling/retries, retained response evidence, strict live
  normalization, and `bootstrap-live` publication through the shared boundary.
- Automated acceptance uses a recording transport and generated source
  snapshot. No live token or live Tushare acceptance was available or claimed.
