# 13 — Recover failed Data publication after restart

**What to build:** Preserve the previous Data truth when collection or
publication fails, then recover durable update state safely after process loss.

**Blocked by:** 11.

**Status:** ready-for-agent

- [ ] Collection, upload, manifest, transaction, stale-worker, and verified-read
  failures expose no partial Dataset Release.
- [ ] The previous latest Release remains authoritative after every failure.
- [ ] An upload followed by rollback leaves only an invisible orphan.
- [ ] Eligible abandoned work can resume after worker restart without duplicate
  Release publication.
- [ ] Exhausted bounded retry records a sanitized `failed` outcome while a later
  Update may still be admitted.
- [ ] Data overview correctly distinguishes `idle`, `updating`, and `failed`,
  includes the latest terminal outcome, and survives HTTP and worker restart.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with failure
  injection at collection, upload, PostgreSQL commit, and stale-worker seams.
- Restart HTTP and worker processes between acceptance and completion; confirm
  the receipt, prior latest Release, failure, and later recovery remain correct.

## Comments
