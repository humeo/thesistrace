# 08 — Bootstrap a Head through the private Data Operator

**What to build:** Let a Data Operator explicitly build the first validated
Dataset Head for an empty development store through a private command, while
ordinary application startup remains read-only and network-independent.

**Blocked by:** 05 — Expand Liquidity only at Dataset Coverage Start; 07 — Select and protect one Dataset Head atomically.

**Status:** ready-for-agent

- [ ] A versioned deployment-private command can Bootstrap an empty valid store and is not registered in the ordinary HTTP router or Web application.
- [ ] With a frozen operator as-of instant and Research Calendar, the default source request begins one natural year earlier and ends at the latest completed Research Session; this operator convenience creates no Research Period minimum, fixed Warm-up, or 756-session requirement.
- [ ] A deterministic source adapter builds a complete candidate, applies Canonical validation and Dataset Bootstrap Expansion, finalizes the Generation, and atomically establishes the first Head.
- [ ] Bootstrap records internal preparation time; public `last_refresh_at` remains null because Bootstrap is not a Data Refresh.
- [ ] Repeating the same idempotency key returns the same outcome without building competing candidates or duplicate Heads; Bootstrap refuses to overwrite an existing valid Head.
- [ ] Collection, normalization, Canonical validation, or Generation materialization failure before Head establishment leaves no Head, keeps readiness false, and exposes no partial Generation; a Head compare-and-swap loser preserves the winner, exposes no partial candidate, and returns or retries safely under its operation identity.
- [ ] Normal API, Worker, and container startup against either an empty or prepared mount never Bootstrap and never call the source.
- [ ] Default verification uses a deterministic Tushare Stub or Replay, while credentials and live response compatibility remain a separate explicitly invoked operator gate.
