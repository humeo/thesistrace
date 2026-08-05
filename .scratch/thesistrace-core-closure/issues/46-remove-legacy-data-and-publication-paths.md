# 46 — Remove legacy Data and Publication paths

**What to build:** Delete the old Data lifecycle, persistence, source-selection,
and publication paths after the canonical Data and Publication modules own the
complete product path.

**Blocked by:** 45.

**Status:** ready-for-agent

- [ ] Old Data Update, Release, source-selection, and publication callers are
  removed without deleting the canonical DataSource adapters.
- [ ] Old filesystem object, metadata facade, release mutation, and provider-mode
  publication entrypoints have no remaining caller.
- [ ] Legacy Data and publication tests are removed or migrated to the canonical
  Data product and shared Publication contracts.
- [ ] No fallback can publish a Dataset Release through SQLite, filesystem
  objects, a custom server, or an old source-specific route.
- [ ] Canonical Fixture and Tushare DataSource adapters, PostgreSQL Releases,
  standard S3 Publication, verified reads, and Data Web behavior remain
  unchanged.
- [ ] Shared canonical-data and quantitative code still used by the Core is
  preserved rather than deleted with its old caller.

**How to verify:**

```sh
set -eu

for removed_path in \
  src/thesistrace/api.py \
  src/thesistrace/datasets.py \
  src/thesistrace/platform_publications.py \
  src/thesistrace/canonical_objects.py \
  src/thesistrace/publication_object_index.py \
  src/thesistrace/tushare_source.py \
  tests/acceptance/test_canonical_parquet_releases.py \
  tests/acceptance/test_dataset_contract.py \
  tests/acceptance/test_empty_workspace.py \
  tests/acceptance/test_fixture_bootstrap.py \
  tests/acceptance/test_incremental_releases.py \
  tests/acceptance/test_parquet_objects.py \
  tests/acceptance/test_tushare_source.py
do
  test ! -e "$removed_path"
done

if rg -n \
  --glob '!web/node_modules/**' \
  --glob '!web/dist/**' \
  'thesistrace\.(api|datasets|platform_publications|canonical_objects|publication_object_index|tushare_source)|DatasetPublisher|/api/v1/(dataset-releases|sources/tushare|objects)' \
  pyproject.toml uv.lock Makefile src scripts tests/adapters tests/integration web
then
  echo 'Legacy Data or Publication path remains reachable' >&2
  exit 1
fi

test -f src/thesistrace/data/service.py
test -f src/thesistrace/adapters/fixture_data.py
test -f src/thesistrace/adapters/tushare_data.py
test -f src/thesistrace/adapters/tushare_provider.py
test -f src/thesistrace/publication/service.py

uv run pytest -q tests/architecture tests/adapters

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/integration tests/acceptance/test_core_data_*.py \
  tests/acceptance/test_core_fixture_data_update.py \
  tests/acceptance/test_core_later_data_update.py \
  tests/acceptance/test_core_no_change_data_update.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

## Comments
