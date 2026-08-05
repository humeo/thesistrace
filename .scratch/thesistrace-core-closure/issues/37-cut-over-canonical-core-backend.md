# 37 — Cut over the canonical Core backend

**What to build:** Make the module-first HTTP and worker composition the only
active backend path while leaving old source present but unreachable for later
controlled contraction.

**Blocked by:** 12, 13, 14, 23, 24, 25, 31, 32, 34, 35, 36.

**Status:** complete

**Implementation:** complete

- [x] Every public resource URL and action resolves only through the new Data,
  Definitions, ResearchRuns, and DailyTracks modules.
- [x] Worker startup invokes only module-owned Data, ResearchRun, and DailyTrack
  processors.
- [x] Active assembly contains no Local/Hosted selection, authentication,
  SQLite, Temporal, outbox, relay, or global dispatch branch.
- [x] Product modules use declared private interfaces rather than cross-schema
  SQL, global metadata, or Hosted imports.
- [x] The same configuration shape addresses PostgreSQL and any standard
  S3-compatible endpoint without choosing a product mode.
- [x] Old backend paths remain in the tree only as unreachable contraction
  targets; this ticket deletes none of them.
- [x] Restarting the canonical HTTP and workers preserves all four product
  resources and authoritative publications.

**How to verify:**

Run the ticket verification against real PostgreSQL and RustFS, then remove the
isolated runtime even if a check fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_backend_cutover.py \
  tests/acceptance/test_core_empty_runtime_restart.py \
  tests/architecture/test_core_runtime_boundaries.py
```

The architecture tests must prove that the default `thesistrace-api` and
`thesistrace-worker` console commands resolve directly to the canonical HTTP
and worker entrypoints. Their complete import graph and runtime assembly must
not load the old API/worker, Hosted, authentication, SQLite, Temporal, outbox,
relay, global dispatch, deployment-mode, or product-mode paths. Explicitly
named inactive Hosted contraction commands and their source may remain until
their deletion tickets, but neither default command may select or fall back to
them. `CoreSettings` must expose one PostgreSQL plus standard S3-compatible
configuration shape with no Local/Hosted selector.

The cutover acceptance must use only the canonical HTTP adapter and module
worker processor to publish Fixture Data, create one Definition, complete one
ResearchRun, and activate one DailyTrack. It must capture the four public
resource projections and their authoritative publication references, start a
fresh HTTP runtime, invoke a fresh canonical worker process through the default
worker command, and prove every projection and publication is unchanged.

The same acceptance must inspect the complete public route inventory: every
Data, Definitions, ResearchRuns, and DailyTracks URL/action resolves through
the canonical adapter, while no old lifecycle, authentication, Hosted,
workspace, operation, raw object, cache, manifest, dispatch, or deployment URL
is registered. Process evidence must show only the canonical entrypoint and
module-owned Data, ResearchRun, and DailyTrack processors were imported; no
legacy or Hosted backend module may execute.

## Comments

- The executable verification contract was committed first in `f5b9ba7`.
  `ad5a77f` repointed the default `thesistrace-api` and
  `thesistrace-worker` commands to the canonical entrypoints and added closed
  route/import/restart acceptance without deleting contraction source.
- Review round 1 found that the populated flow had processed work through test
  helpers before invoking the default worker, and that the restart snapshot
  omitted owning-module publication references. `3837bed` changed the test to
  enqueue only through HTTP and use the actual default worker for first Data,
  ResearchRun, later Data, and DailyTrack progression; it also captured Data,
  ResearchRun, DailyTrack, Checkpoint, and Publication references.
- Review round 2 passed Standards but found two Spec gaps: the
  manifest-to-object association and non-`/api` application routes were not in
  the inventories. `908e3e3` added `publication.manifest_objects`, reopened all
  Dataset Release and Definition details, and enumerated every application
  route while excluding only the four exact FastAPI framework endpoints.
- Review round 3 passed Standards and Spec with zero findings. It confirmed the
  default process seams, import exclusions, module workers, complete route
  inventory, authoritative reference snapshot, test isolation, and the
  intentional boundary that Web switching/deletion remains in Tickets 38–39.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed with `23 passed, 1 warning in 39.15s`;
  the trap removed both runtime containers afterward.
- The repository browser gate intentionally remains on the old Web until
  Ticket 38 switches the four-resource Shell. The full `make check` is run at
  that boundary rather than reactivating an old backend merely to keep the
  transitional browser command green.
