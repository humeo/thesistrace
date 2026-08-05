# 41 — Remove Hosted operations and observability runtime

**What to build:** Delete inactive Hosted operations, capacity, and launch
machinery so operational scope cannot block or leak into the Core product.

**Blocked by:** 40.

**Status:** complete

- [x] The Hosted archive ref is reverified before deletion.
- [x] Quota profiles, hosted admission policy, disk-pressure modes, maintenance,
  backup, restore, rollback, and launch-qualification runtime code are removed.
- [x] Hosted health dashboards, alerting, release evidence, and operator
  telemetry services are removed with their callers, targets, dependencies, and
  tests.
- [x] Core product states and sanitized failure reasons remain available without
  an Operations Ledger or System Health product.
- [x] Historical operations ADRs and research remain recoverable but are marked
  clearly outside the active Core.
- [x] The default Core gate requires no capacity or production-launch evidence.

**How to verify:**

```sh
test "$(git show-ref --hash refs/archive/hosted-v2-pre-core-closure)" = \
  2884f96ecd1f3aed1e16b00116d54a99c9def89a
git cat-file -e \
  refs/archive/hosted-v2-pre-core-closure:src/thesistrace/hosted/health_service.py
git cat-file -e \
  refs/archive/hosted-v2-pre-core-closure:src/thesistrace/hosted/backup_operations.py

for removed_path in \
  src/thesistrace/capacity.py \
  src/thesistrace/launch.py \
  src/thesistrace/qualification.py \
  src/thesistrace/quota.py \
  src/thesistrace/storage_admission.py \
  src/thesistrace/hosted/backup_cli.py \
  src/thesistrace/hosted/backup_operations.py \
  src/thesistrace/hosted/capacity_corpus.py \
  src/thesistrace/hosted/health_service.py \
  src/thesistrace/hosted/observability.py \
  src/thesistrace/hosted/operator_audit.py \
  src/thesistrace/hosted/probes.py \
  src/thesistrace/hosted/release_cli.py \
  src/thesistrace/hosted/release_gate.py \
  src/thesistrace/hosted/release_operations.py \
  deploy/hosted/otel-collector.yaml \
  deploy/hosted/prometheus.yaml \
  deploy/hosted/grafana \
  deploy/hosted/systemd/thesistrace-backup.service \
  deploy/hosted/systemd/thesistrace-backup.timer \
  tests/hosted/test_backup_cli.py \
  tests/hosted/test_backup_operations.py \
  tests/hosted/test_health_postgres.py \
  tests/hosted/test_health_views.py \
  tests/hosted/test_launch_qualification.py \
  tests/hosted/test_quota_profile.py \
  tests/hosted/test_release_operations.py \
  tests/hosted/test_storage_admission.py
do
  test ! -e "$removed_path"
done

! rg -n \
  --glob '!deploy/hosted/migrations/*.sql' \
  --glob '!docs/adr/*.md' \
  --glob '!docs/research/*.md' \
  --glob '!docs/archive/*.md' \
  --glob '!docs/runbook/hosted-health.md' \
  --glob '!docs/runbook/v1-operations.md' \
  'thesistrace-health-service|thesistrace-release|health-service|backup-tool|restore-tool|restore-gate|otel-collector|prometheus|grafana|opentelemetry|CapacityQualification|LaunchQualification|QuotaProfileService|DiskPressurePolicy|Operations Ledger|System Health|maintenance-enter|maintenance-exit|hosted-rollback|hosted-backup|hosted-restore' \
  pyproject.toml uv.lock Makefile src scripts deploy/hosted tests

uv run python - <<'PY'
from pathlib import Path

for path in (
    Path("docs/runbook/hosted-health.md"),
    Path("docs/runbook/v1-operations.md"),
):
    source = path.read_text().lower()
    assert "archived" in source
    assert "outside the active core" in source
PY

sh -n scripts/hosted-stack
docker compose -f deploy/hosted/compose.yaml config --quiet
uv run pytest -q tests/hosted

uv run pytest -q tests/architecture tests/integration tests/acceptance

set -eu
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_backend_cutover.py \
  tests/acceptance/test_core_research_run_execution.py \
  tests/acceptance/test_core_daily_track_advance.py
```

## Comments

- Archive reverified at
  `2884f96ecd1f3aed1e16b00116d54a99c9def89a`; both required archived blobs
  resolve. The removed-path inventory, forbidden-token scan, archived runbook
  assertions, launcher shell parse, and Compose config checks pass.
- Implementation: `33a7001`; review fixes: `6c608ae`, `47bde56`, and `33c94ca`.
  The forward `0028` and `0029` migrations remove the retired health,
  maintenance, qualification, quota, and admission database state while
  preserving the retained resource-deletion contract.
- A fresh isolated Hosted PostgreSQL/InsForge schema applied migrations
  `0001` through `0029` successfully. Direct database queries confirmed that
  the retired role, tables, functions, triggers, and admission caller are gone;
  the remaining one-shot management role has invitation read/insert/update but
  no delete privilege. The isolated containers, network, and volumes were
  removed afterward.
- `uv run pytest -q tests/hosted`: `49 passed, 7 skipped, 1 warning`.
- `uv run pytest -q tests/architecture tests/integration tests/acceptance`:
  `97 passed, 96 skipped, 1 warning`.
- The isolated PostgreSQL/RustFS Core command in **How to verify**:
  `5 passed, 1 warning`; its cleanup trap removed both test containers.
- Independent review round 3 over `950c61e..33c94ca`: Standards **PASS** and
  Spec **PASS**, with no actionable P0-P3 findings.
