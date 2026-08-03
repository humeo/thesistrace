# 43 — Remove custom storage proxies and Hosted glue

**What to build:** Delete the remaining self-built object-store, network proxy,
and Hosted glue after every Hosted and old-Web caller is gone.

**Blocked by:** 42.

**Status:** ready-for-agent

- [ ] The custom object-store HTTP service, storage-token protocol, remote
  filesystem proxy, and Hosted-only Tushare egress proxy are removed.
- [ ] Hosted runtime-mode configuration, shared startup glue, remaining Hosted
  entrypoints, dependencies, scripts, Make targets, and tests are removed when
  no caller remains.
- [ ] Core Publication still uses only the standard S3 client against the
  configured endpoint.
- [ ] Canonical Tushare remains a direct DataSource adapter and creates no
  product mode.
- [ ] No Core response exposes a replacement storage or proxy protocol.
- [ ] The Hosted archive and historical ADR/research material remain intact.

**How to verify:**

- Run `uv run pytest -q tests/architecture tests/adapters tests/integration`
  with only PostgreSQL, RustFS, and canonical Core processes available.
- Inspect installed entrypoints, dependencies, scripts, and targets; all
  Hosted-only glue must be absent and the standard S3/DataSource paths must pass.

## Comments
