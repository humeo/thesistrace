# 38 — Cut over the four-resource Web Shell

**What to build:** Make the new Data, Definitions, ResearchRuns, and DailyTracks
modules the only active browser product while keeping old files untouched until
replacement acceptance passes.

**Blocked by:** 37.

**Status:** ready-for-agent

- [ ] Stable routes are `/data`, `/definitions`, `/definitions/:id`,
  `/research-runs`, `/research-runs/:id`, `/daily-tracks`, and
  `/daily-tracks/:id`.
- [ ] The Shell owns navigation and current-route composition only.
- [ ] Each resource module owns its list, detail, actions, typed requests,
  loading, refresh, empty, and error behavior.
- [ ] Run sends current editor content directly; no Web sequence performs Save
  and then Run as separate product actions.
- [ ] Resource refresh stays local to the active Update, Run, or Track instead
  of a global polling loop.
- [ ] Visible navigation completes Data Update, incomplete Save, rejected Run,
  successful Run/Result, edited Run, Rerun, Cancel, Track activation, later
  Release advance, blocked Retry, and Stop against the canonical backend.
- [ ] This ticket switches the active UI but deletes no old Web or authentication
  source.

**How to verify:**

- Run `bun run --cwd web typecheck`, `bun run --cwd web build`, and
  `bun run --cwd web test:e2e` against the real canonical backend.
- Manually navigate every stable route in the desktop browser and confirm the
  complete visible Core loop never leaves the four-resource Shell.

## Comments
