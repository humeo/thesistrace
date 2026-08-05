# 47 — Remove orphaned legacy infrastructure

**What to build:** Contract the remaining shared legacy infrastructure and the
temporary expression adapter only after every active caller has migrated.

**Blocked by:** 46.

**Status:** complete

- [x] SQLite Product State and its runtime assembly are removed.
- [x] Global metadata ports, repository-per-table interfaces, generic command
  envelopes, no-op dispatch seams, and old lifecycle facades are removed.
- [x] The temporary string-expression compatibility boundary is removed after
  every active caller uses the normalized tree.
- [x] Orphaned old HTTP, storage, tracking, worker, configuration, dependencies,
  scripts, and tests are deleted rather than wrapped.
- [x] One PostgreSQL and standard-S3 Core implementation remains; there is no
  runtime-mode selector or hidden fallback.
- [x] Current documentation and default targets describe only the active Core,
  while ADR and archived history remain preserved.

**How to verify:**

```sh
set -eu

for removed_path in \
  src/thesistrace/config.py \
  src/thesistrace/runtime.py \
  src/thesistrace/storage.py \
  src/thesistrace/worker.py \
  src/thesistrace/objects.py \
  src/thesistrace/ports.py \
  src/thesistrace/management.py \
  src/thesistrace/activity_contract.py \
  src/thesistrace/alpha.py \
  src/thesistrace/factor.py \
  src/thesistrace/strategy.py \
  src/thesistrace/numeric.py \
  tests/kernel/test_alpha.py \
  prototypes/run-storage-budget/README.md \
  prototypes/run-storage-budget/validate.py \
  docs/runbook/v1-operations.md \
  docs/runbook/hosted-compose.md \
  docs/runbook/hosted-health.md
do
  test ! -e "$removed_path"
done

legacy_hits="$(
  rg -n \
    --glob '!web/node_modules/**' \
    --glob '!web/dist/**' \
    --glob '!src/thesistrace/*/migrations.py' \
    --glob '!tests/acceptance/test_core_contraction_migration.py' \
    'thesistrace\.(config|runtime|storage|worker|objects|ports|management|activity_contract|alpha|factor|strategy|numeric)|MetadataStore|ImmutableObjectStore|RuntimePorts|LocalWorkerDispatch|ExecutionDispatchPort|LegacyStartTrackingReceipt|activation_receipts|authorable_field_bindings_from_snapshot|sqlite3' \
    pyproject.toml uv.lock Makefile src scripts \
    tests/kernel tests/adapters tests/integration tests/acceptance web || {
      rg_status=$?
      test "$rg_status" -eq 1 || exit "$rg_status"
    }
)"
if test -n "$legacy_hits"; then
  printf '%s\n' "$legacy_hits"
  echo 'A second runtime or legacy facade remains reachable' >&2
  exit 1
fi

if rg -n \
  'validate_legacy_alpha|FIELD_PATTERN|legacy string|isinstance\(expression, str\)|type AlphaExpression = str' \
  src/thesistrace/research_kernel tests/kernel
then
  echo 'The temporary string-expression adapter remains reachable' >&2
  exit 1
fi

if rg -n -i \
  'metadata\.sqlite3|local metadata and immutable objects|/api/v1/dataset-releases|/api/v1/sources/tushare' \
  README.md docs/architecture docs/runbook
then
  echo 'Current documentation still describes a removed runtime' >&2
  exit 1
fi

uv run pytest -q tests/kernel tests/architecture tests/adapters
bun run --cwd web typecheck
bun run --cwd web build

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q tests/integration tests/acceptance
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

## Comments

- Implementation: `3fe1127`; review fixes: `a3ec033`, `f37a86d`, `23e9c12`.
- The old SQLite/storage/ports/worker/facade cluster and the prototype that
  exercised it were deleted. Hosted/V1 runbooks moved under `docs/archive/`;
  current README, architecture, Make targets, and Tushare guide describe only
  PostgreSQL, standard S3, Fixture development, and the optional live adapter
  credential gate.
- Alpha input is normalized-tree-only at validation, `RunInput` construction,
  immutable snapshot, Kernel tests, and DailyTrack state. Exact tests freeze
  every operator's values plus missing, non-finite, divide-by-zero, and
  deterministic matrix behavior.
- Independent review round 1 found the active legacy Start Tracking receipt
  cutover, a residual string snapshot seam, an orphan field fallback, weakened
  operator tests, two archive defects, and a fallible negative scan. All were
  removed or corrected.
- Review round 2 found rewritten published migration statements. Historical
  DailyTrack migrations were restored byte-for-byte; append-only ResearchRun
  and DailyTrack contraction migrations now transfer any old receipts and then
  drop the old table without reintroducing startup/service compatibility code.
- Review round 3 found that the upgrade test built its old ledger from the
  current plan. The final test freezes SHA256 for all 12 published migrations,
  then proves the old ledger forwards, preserves the receipt, and removes the
  table on real PostgreSQL. This post-review correction was verified directly;
  the three-round review cap was not extended.
- Final exact verification: all removal and active-document scans passed;
  Kernel/Architecture/Adapter `137 passed`; Web typecheck and production build
  passed; isolated Integration/Acceptance `98 passed` in `1283.38s` with one
  dependency deprecation warning; clean-reset Web E2E `18 passed` in `2.7m`.
