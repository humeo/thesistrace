# 40 — Remove Hosted execution and orchestration

**What to build:** Delete the inactive Temporal, dispatch, outbox, relay, and
Hosted worker execution path while preserving canonical PostgreSQL workers.

**Blocked by:** 01, 38.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before deletion.
- [ ] Temporal workflows, activities, task queues, execution relay, dispatch
  queue, outbox, and Hosted compute workers are removed with their callers.
- [ ] Hosted-only execution entrypoints, dependencies, targets, and tests are
  removed in the same contraction.
- [ ] Remaining Hosted operations and deployment files no longer import or
  invoke the removed execution path, without deleting those files early.
- [ ] Core ResearchRun and DailyTrack execution continue only through their
  PostgreSQL-owned processors.
- [ ] No active source, configuration, or default gate imports or starts the
  removed orchestration path.
- [ ] Accepted quantitative behavior and immutable publications remain
  unchanged.

**How to verify:**

Run the contraction inventory and canonical-worker acceptance with no Temporal,
relay, or Hosted worker service available. The trap must remove the isolated
PostgreSQL/RustFS runtime even if a later check fails:

```sh
set -eu
archive_commit=2884f96ecd1f3aed1e16b00116d54a99c9def89a
test "$(git show-ref --hash refs/archive/hosted-v2-pre-core-closure)" = \
  "$archive_commit"
git cat-file -e "$archive_commit:src/thesistrace/hosted/temporal_worker.py"
git cat-file -e "$archive_commit:src/thesistrace/hosted/execution_relay.py"

for removed_path in \
  deploy/hosted/temporal \
  deploy/hosted/compose.local.yaml \
  scripts/hosted/capacity_qualification.py \
  scripts/hosted/local_acceptance.py \
  scripts/hosted/local_boundary_acceptance.py \
  scripts/hosted/local_frontend_acceptance.py \
  scripts/hosted/local_ops_probe.py \
  scripts/hosted/local_postgres_acceptance.py \
  scripts/hosted/local_recovery_acceptance.py \
  scripts/hosted/temporal_dispatch_probe.py \
  scripts/hosted/local_workflow_acceptance.py \
  scripts/hosted/record_launch_qualification.py \
  scripts/hosted/release_acceptance.py \
  src/thesistrace/hosted/activity_heartbeat.py \
  src/thesistrace/hosted/activity_policy.py \
  src/thesistrace/hosted/capacity_probe.py \
  src/thesistrace/hosted/capacity_workflow.py \
  src/thesistrace/hosted/compute_dispatch.py \
  src/thesistrace/hosted/data_worker.py \
  src/thesistrace/hosted/dataset_publication_workflow.py \
  src/thesistrace/hosted/execution_outbox.py \
  src/thesistrace/hosted/execution_relay.py \
  src/thesistrace/hosted/research_workflow.py \
  src/thesistrace/hosted/temporal_recovery_probe.py \
  src/thesistrace/hosted/temporal_worker.py \
  src/thesistrace/hosted/tracking_operations_workflow.py \
  src/thesistrace/hosted/tracking_workflow.py \
  tests/hosted/test_capacity_qualification.py \
  tests/hosted/test_compute_dispatch.py \
  tests/hosted/test_dataset_publication_workflow.py \
  tests/hosted/test_research_workflow.py \
  tests/hosted/test_temporal_worker_heartbeat.py \
  tests/hosted/test_tracking_operations_workflow.py \
  tests/hosted/test_tracking_workflow.py \
  tests/hosted/test_local_acceptance.py; do
  test ! -e "$removed_path"
done

! rg -n \
  'temporal|thesistrace-execution-relay|execution-relay|execution_relay|execution_outbox|compute-worker|data-worker|thesistrace-recovery-probe|recovery-probe|recovery_probe|dispatch-probe|dispatch_probe|hosted-local-smoke|local_workflow_acceptance|thesistrace_relay|workflow_capacity|workflow_running|tracking-generation-rebuild|hosted-local-acceptance|hosted-release-acceptance|acceptance-record-launch' \
  pyproject.toml uv.lock Makefile src/thesistrace/config.py \
  src/thesistrace/capacity.py src/thesistrace/launch.py \
  src/thesistrace/hosted scripts deploy/hosted \
  --glob '!deploy/hosted/migrations/*.sql'

git ls-tree -r --name-only "$archive_commit" deploy/hosted/migrations |
while IFS= read -r migration_file; do
  test "$(git show "$archive_commit:$migration_file" | shasum -a 256 | cut -d' ' -f1)" = \
    "$(shasum -a 256 "$migration_file" | cut -d' ' -f1)"
done
test -f deploy/hosted/migrations/0027_remove_hosted_execution.sql
test "$(jq -r '.components.product_migrations.version' deploy/hosted/release.json)" = 0027

uv run pytest -q tests/architecture tests/kernel
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_backend_cutover.py \
  tests/acceptance/test_core_research_run_execution.py \
  tests/acceptance/test_core_daily_track_advance.py
```

The installed dependency and console-script inventories must contain no
Temporal client, Hosted execution relay, recovery probe, or compute/data worker
entrypoint. Remaining Hosted operations and deployment files may stay for the
next contraction tickets, but they must not import, configure, start, probe,
back up, restore, or report the removed execution path.

The architecture and real-runtime acceptance must show that the default worker
uses only the PostgreSQL-owned ResearchRuns and DailyTracks processors, while
the accepted quantitative calculations and immutable Publication references
remain unchanged.

## Comments
