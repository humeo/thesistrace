# 45 — Remove legacy Definition and ResearchRun paths

**What to build:** Delete old Definition, Save/Run, ResearchRun lifecycle, and
Result paths after the canonical modules own every active research action.

**Blocked by:** 44.

**Status:** complete

- [x] Draft, separately browsable frozen version, old Save-then-Run sequencing,
  and legacy Definition routes are removed.
- [x] Old ResearchRun creation, execution, Result, Cancel, Rerun, and internal
  lifecycle projections are removed with their callers.
- [x] Legacy Definition and ResearchRun tests are removed or migrated to the
  mutable Definition, atomic Run, immutable-input, and bounded Result contracts.
- [x] No path can create a ResearchRun outside Definition Run or ResearchRun
  Rerun, and no generic create, update, or delete route remains.
- [x] Canonical Definition revision handling, Run receipts, PostgreSQL worker,
  standard S3 Publication, Cancel fencing, and exact-input Rerun remain
  unchanged.
- [x] Quantitative code now owned by the Research Kernel is preserved rather
  than deleted with an old lifecycle caller.

**How to verify:**

```sh
set -eu

for removed_path in \
  src/thesistrace/definitions.py \
  src/thesistrace/research_runs.py \
  src/thesistrace/bounded_research.py \
  src/thesistrace/result_objects.py \
  src/thesistrace/resource_deletion.py \
  tests/acceptance/test_bounded_research.py \
  tests/acceptance/test_research_definitions.py \
  tests/acceptance/test_research_runs.py \
  tests/acceptance/test_resource_deletion.py \
  tests/acceptance/test_result_bundle_capacity.py \
  tests/acceptance/test_runtime_ports.py
do
  test ! -e "$removed_path"
done

if rg -n \
  --glob '!docs/adr/*.md' \
  --glob '!docs/research/*.md' \
  --glob '!docs/archive/*.md' \
  --glob '!web/node_modules/**' \
  --glob '!web/dist/**' \
  'thesistrace\.(definitions|research_runs|bounded_research|result_objects|resource_deletion)|ResearchDefinitionService|recover_staged_research_run|/api/v1/research-(definitions|definition-versions|runs)' \
  pyproject.toml uv.lock Makefile src scripts tests web
then
  echo 'Legacy Definition or ResearchRun path remains reachable' >&2
  exit 1
fi

test -f src/thesistrace/definition/service.py
test -f src/thesistrace/research_run/service.py
test -f src/thesistrace/research_kernel/kernel_run.py

uv run pytest -q tests/architecture/test_core_runtime_boundaries.py \
  -k legacy_definition_and_research_run_modules_are_absent

uv run pytest -q tests/kernel tests/architecture

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/integration tests/acceptance/test_core_definition_*.py \
  tests/acceptance/test_core_research_run_*.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

## Comments

- Implementation: `5d9d2c1`; verification corrections and review fix:
  `74fd7cc`, `21b548f`.
- The first literal verification attempt stopped before tests because the
  Ticket named `research_kernel/run.py`; the Ticket was corrected to the real
  `research_kernel/kernel_run.py` path before the complete rerun.
- Independent review round 1: Standards FAIL / Spec FAIL. It found the wrong
  Kernel path and a route guard coupled to single-line decorator formatting.
- The route invariant now parses FastAPI decorators with Python AST and proves
  both allowed Run/Rerun paths plus the absence of generic ResearchRun
  POST/PUT/DELETE routes.
- Independent review round 2: Standards PASS / Spec PASS; no remaining P0-P3.
- Final exact verification: route invariant `1 passed, 21 deselected`; Kernel
  and architecture `90 passed`; isolated integration and canonical Definition /
  ResearchRun acceptance `55 passed` (one dependency deprecation warning);
  clean-reset Web E2E `18 passed`.
