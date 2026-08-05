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

Run the default Web verification against real PostgreSQL, RustFS, canonical
HTTP, and canonical workers, then remove the isolated runtime even if a check
fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
bun run --cwd web typecheck
bun run --cwd web build
bun run --cwd web test:shell
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

The default `index.html`, `src/main.tsx`, `bun run dev`, and `bun run test:e2e`
must resolve only to the four-resource Core Shell and the canonical backend
commands. `/` may replace its own history entry with `/data`; it must not render
or bundle the old application or Hosted authentication boundary. Old Web and
authentication files remain untouched as inactive deletion targets for Ticket
39. The active bundle must use statically analyzable direct imports and contain
no runtime product-mode branch.

The default browser suite must navigate `/data`, `/definitions`, one stable
`/definitions/:id`, `/research-runs`, one stable `/research-runs/:id`,
`/daily-tracks`, and one stable `/daily-tracks/:id`. At every route the Shell
must expose exactly four resource links and only the active resource module.
No old workspace, login, Hosted, operations, raw JSON, download, manifest,
object, worker, cache, deployment, Draft, frozen-version, Attempt, Generation,
Advance, or Checkpoint surface may appear.

Across the named browser cases, visible navigation must prove Data Update,
nameless incomplete Save/reopen, invalid Run rejection without a ResearchRun,
valid current-editor Run and bounded Result, edited independent Run, exact-input
Rerun, Cancel, response-loss replay, Start Tracking, later Release automatic
advance, isolated blocked outcome, Retry, and irreversible Stop against the
canonical routes. Run must send the current editor content as one action; no
Save-then-Run Web sequence is allowed. Polling/refresh must remain inside the
active Data Update, ResearchRun, or DailyTrack module rather than a Shell-level
or global loop.

## Comments
