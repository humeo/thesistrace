# 35 — Stop a DailyTrack irreversibly

**What to build:** Let a user permanently stop an active or blocked DailyTrack,
fence in-flight work, and retain its authoritative history.

**Blocked by:** 33.

**Status:** ready-for-agent

- [ ] Stop is accepted from `active` or `blocked` and records the terminal
  `stopped` state atomically.
- [ ] Stop advances the Track fence so late work cannot publish a visible
  Checkpoint or move Head.
- [ ] Disposable Working Cache is removed while Tracking Origin, committed
  Checkpoints, Head, and product history remain readable.
- [ ] A stopped Track does not count toward the active-or-blocked limit.
- [ ] Stopped cannot Retry, reactivate, or advance again.
- [ ] Matching request replay returns stopped; different input conflicts; a
  malformed request creates no receipt.
- [ ] The Web communicates that Stop is irreversible and shows the terminal
  state after refresh and restart.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` for active Stop,
  blocked Stop, replay, conflict, late-worker fencing, cache removal, and
  restart.
- Run `bun run --cwd web test:e2e` and confirm no later Data Update changes the
  stopped Track's Head.

## Comments
