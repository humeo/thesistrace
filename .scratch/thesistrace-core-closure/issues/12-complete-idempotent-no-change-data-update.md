# 12 — Complete an idempotent no-change Data Update

**What to build:** Complete Data Update safely when no new completed Research
Session exists, while enforcing single active work and request replay rules.

**Blocked by:** 10.

**Status:** ready-for-agent

- [ ] A source batch with no new completed Research Session produces the
  terminal `no_change` outcome and no Dataset Release or Publication.
- [ ] PostgreSQL permits at most one active Data Update; concurrent admission
  cannot create duplicate collection work.
- [ ] Repeating the same request ID, action, and fingerprint returns the first
  acceptance or terminal outcome without a new Attempt or Release.
- [ ] Reusing a request ID with different input returns a conflict.
- [ ] A structurally malformed Update request creates no receipt.
- [ ] The Data page presents `no_change` as a successful terminal outcome and
  keeps the existing latest Release.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with repeated,
  conflicting, malformed, and concurrent Update requests.
- Run `bun run --cwd web test:e2e` and confirm a no-change update leaves Release
  history unchanged and reports no failure.

## Comments
