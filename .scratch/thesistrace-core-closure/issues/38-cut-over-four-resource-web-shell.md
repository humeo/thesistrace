# 38 — Cut over the four-resource Web Shell

**What to build:** Make the new Data, Definitions, ResearchRuns, and DailyTracks
modules the only active browser product while keeping old files untouched until
replacement acceptance passes.

**Blocked by:** 37.

**Status:** complete

**Implementation:** complete

- [x] Stable routes are `/data`, `/definitions`, `/definitions/:id`,
  `/research-runs`, `/research-runs/:id`, `/daily-tracks`, and
  `/daily-tracks/:id`.
- [x] The Shell owns navigation and current-route composition only.
- [x] Each resource module owns its list, detail, actions, typed requests,
  loading, refresh, empty, and error behavior.
- [x] Run sends current editor content directly; no Web sequence performs Save
  and then Run as separate product actions.
- [x] Resource refresh stays local to the active Update, Run, or Track instead
  of a global polling loop.
- [x] Visible navigation completes Data Update, incomplete Save, rejected Run,
  successful Run/Result, edited Run, Rerun, Cancel, Track activation, later
  Release advance, blocked Retry, and Stop against the canonical backend.
- [x] This ticket switches the active UI but deletes no old Web or authentication
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

- The executable verification contract was committed first in `2b8fe3b`.
  `716e63f` made `index.html`, `src/main.tsx`, default development, and default
  browser acceptance use the four-resource Shell and canonical commands.
- `edf723e` removed the alternate production Rollup input and added the edited
  current-content Run flow. Review round 1 had identified both omissions.
- Review round 2 found a development-only `/core.html` entry, dead route
  classifier declarations, and insufficient proof that edited Run performs no
  implicit Save. `4f7b7e7` made `/core.html` redirect-only, removed the dead
  declarations, and asserted that the edited action emits exactly one
  Definition write: `POST /api/definitions/:id/run`.
- Review round 3 passed Standards and Spec with zero findings. It confirmed one
  active Vite entry, direct static module imports, Shell-only routing ownership,
  redirect-only legacy entry behavior, and the single-action edited Run.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS. TypeScript checking passed; the production build
  emitted only `dist/index.html` and one product bundle; the Shell unit test
  passed; and all `18` default Playwright flows passed in `1.9m`. The trap
  removed both runtime containers afterward.
- An expanded diagnostic run of the future Ticket 49 Core-enabled repository
  gate exposed an older recovery-test proxy that lacked the later
  `Publication.read` operation. The test-only fix in `71bd456` passed all five
  publication-recovery failure branches and an independent Standards/Spec
  review with zero findings. The full no-skip gate remains Ticket 49's
  orchestration boundary rather than a requirement of this Web cutover.
