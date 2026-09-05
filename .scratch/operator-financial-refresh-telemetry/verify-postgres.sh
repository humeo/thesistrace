#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$test_dir/../.." && pwd)
progress_project="thesistrace-test-financial-progress-$$"
progress_scratch=$(mktemp -d)
compose() { docker compose -p "$progress_project" -f "$test_dir/compose.test.yaml" "$@"; }
cleanup() {
  compose logs --no-color
  compose down --volumes
}
trap cleanup EXIT
compose up --detach --wait --wait-timeout 90
progress_port=$(compose port postgres 5432)
cd "$repo_dir"
THESISTRACE_DATABASE_URL="postgresql://progress_test:isolated-progress-test@${progress_port}/progress_test" \
THESISTRACE_S3_ENDPOINT_URL=http://127.0.0.1:1 \
THESISTRACE_S3_ACCESS_KEY_ID=unused THESISTRACE_S3_SECRET_ACCESS_KEY=unused \
THESISTRACE_S3_BUCKET=unused THESISTRACE_DATA_MOUNT="$progress_scratch/data" \
THESISTRACE_BENCHMARK_MOUNT="$progress_scratch/benchmark" \
THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY="$progress_scratch/attempts" \
uv run pytest -q tests/integration/test_daily_financial_refresh.py \
  tests/integration/test_data_refresh.py::test_operational_status_has_safe_head_latest_kinds_and_stable_fifty_row_pages \
  --junitxml="$progress_scratch/pytest.xml"
