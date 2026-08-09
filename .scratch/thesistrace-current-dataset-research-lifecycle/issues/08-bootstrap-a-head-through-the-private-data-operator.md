# 08 — Bootstrap a Head through the private Data Operator

**What to build:** Let a Data Operator explicitly build the first validated
Dataset Head for an empty development store through a private command, while
ordinary application startup remains read-only and network-independent.

**Blocked by:** 05 — Expand Liquidity only at Dataset Coverage Start; 07 — Select and protect one Dataset Head atomically.

**Status:** complete

- [x] A versioned deployment-private command can Bootstrap an empty valid store and is not registered in the ordinary HTTP router or Web application.
- [x] With a frozen operator as-of instant and Research Calendar, the default source request begins one natural year earlier and ends at the latest completed Research Session; this operator convenience creates no Research Period minimum, fixed Warm-up, or 756-session requirement.
- [x] A deterministic source adapter builds a complete candidate, applies Canonical validation and Dataset Bootstrap Expansion, finalizes the Generation, and atomically establishes the first Head.
- [x] Bootstrap records internal preparation time; public `last_refresh_at` remains null because Bootstrap is not a Data Refresh.
- [x] Repeating the same idempotency key returns the same outcome without building competing candidates or duplicate Heads; Bootstrap refuses to overwrite an existing valid Head.
- [x] Collection, normalization, Canonical validation, or Generation materialization failure before Head establishment leaves no Head, keeps readiness false, and exposes no partial Generation; a Head compare-and-swap loser preserves the winner, exposes no partial candidate, and returns or retries safely under its operation identity.
- [x] Normal API, Worker, and container startup against either an empty or prepared mount never Bootstrap and never call the source.
- [x] Default verification uses a deterministic Tushare Stub or Replay, while credentials and live response compatibility remain a separate explicitly invoked operator gate.

## Comments

- Implemented by `14d29d8 feat(data): bootstrap mounted head privately`; review hardening is in `d4ac590`, `0ab7462`, `04f5c00`, `cd48962`, and `10e0f95`.
- `thesistrace-data-operator-v1 bootstrap` is a private command/process boundary. It freezes a Shanghai-aware one-natural-year plan, collects either live Tushare or a bounded Replay, validates Canonical data after Dataset Bootstrap Expansion, materializes one Generation, and establishes the first Head by fenced CAS.
- Bootstrap idempotency is durable in PostgreSQL. Owner-token leases heartbeat throughout remote collection and materialization; takeover, old-candidate revocation, candidate recording, and Head CAS share the Data Lifecycle fence, so a stale process cannot publish or overwrite the winning operation.
- Head preparation time is recorded at the successful atomic publication boundary, independently from candidate materialization metadata. Bootstrap creates no Refresh timestamp or public mutation surface, and the CLI emits only stable sanitized failure codes.
- Focused source, adapter, Head, architecture, and live-gate tests passed (`75 passed in 27.16s` in the broad focused run; the final live-gate contract passed `6 passed`). A fresh real PostgreSQL/RustFS run passed Bootstrap concurrency, heartbeat, crash recovery, migration, and lifecycle tests (`10 passed in 29.60s`). Ruff and diff checks passed.
- `./scripts/smoke-data-operator-image` built the Production backend image, ran the operator twice against a shared named mount with one deterministic Replay, started and restarted API/Worker without source credentials, and reopened the same Head. Both isolated smoke projects and the dedicated integration project removed their containers, networks, and volumes afterward.
- Standards and Spec reviews used fixed point `69f1596..10e0f95` and both ended with zero findings.
