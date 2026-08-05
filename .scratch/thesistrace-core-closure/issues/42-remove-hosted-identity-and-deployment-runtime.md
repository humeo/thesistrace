# 42 — Remove Hosted identity and deployment runtime

**What to build:** Delete inactive login, tenant, and hosted-deployment runtime
code while retaining deferred identity and deployment decisions as history.

**Blocked by:** 39, 41.

**Status:** ready-for-agent

- [ ] The Hosted archive ref is reverified before deletion.
- [ ] InsForge authentication integration, Auth Session runtime, User,
  Personal Workspace, invitation, tenancy, and RLS enforcement code are removed
  from the active product.
- [ ] Hosted deployment runtime, Cloudflare, Caddy, hosted Compose, rollout, and
  release-migration machinery are removed with their active targets and tests.
- [ ] Core resource shapes, URLs, and actions retain no ownership or identity
  placeholder branch.
- [ ] ADR and research history remain available; deferred identity material is
  clearly not an active Core requirement.
- [ ] Core still starts as one instance-owned product without login.

**How to verify:**

```sh
test "$(git show-ref --hash refs/archive/hosted-v2-pre-core-closure)" = \
  2884f96ecd1f3aed1e16b00116d54a99c9def89a
git cat-file -e \
  refs/archive/hosted-v2-pre-core-closure:src/thesistrace/auth.py
git cat-file -e \
  refs/archive/hosted-v2-pre-core-closure:deploy/hosted/compose.yaml

for removed_path in \
  deploy/hosted \
  scripts/hosted-stack \
  scripts/hosted-auth-smoke.py \
  scripts/hosted-release-smoke.py \
  scripts/hosted-smoke.py \
  scripts/hosted/configure_smtp.py \
  scripts/hosted/seed_acceptance_state.py \
  src/thesistrace/auth.py \
  src/thesistrace/operator.py \
  src/thesistrace/provisioning.py \
  src/thesistrace/tenancy.py \
  src/thesistrace/hosted/control.py \
  src/thesistrace/hosted/management.py \
  src/thesistrace/hosted/migrations.py \
  src/thesistrace/hosted/provisioning.py \
  src/thesistrace/hosted/runtime.py \
  tests/hosted/test_compose_stack.py \
  tests/hosted/test_container_boundaries.py \
  tests/hosted/test_daily_track_lifecycle.py \
  tests/hosted/test_edge_policy.py \
  tests/hosted/test_edge_rate_limits.py \
  tests/hosted/test_insforge_auth.py \
  tests/hosted/test_registration_provisioning.py \
  tests/hosted/test_source_authorization.py \
  tests/hosted/test_workspace_isolation.py
do
  test ! -e "$removed_path"
done

! rg -n \
  --glob '!docs/adr/*.md' \
  --glob '!docs/research/*.md' \
  --glob '!docs/archive/*.md' \
  'InsForge|Personal Workspace|THESISTRACE_AUTH_MODE|auth_mode|insforge_|thesistrace-operator|hosted-(up|deploy|down|restart|smoke|smtp-configure|config|operator)' \
  pyproject.toml uv.lock Makefile src scripts tests web

! rg -n \
  'workspace_id|personal_workspace|user_id|auth_session|login|hosted' \
  src/thesistrace/data \
  src/thesistrace/definition \
  src/thesistrace/research_run \
  src/thesistrace/daily_track \
  src/thesistrace/publication \
  src/thesistrace/entrypoints \
  web/src

uv run pytest -q tests/architecture tests/integration tests/acceptance

set -eu
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

## Comments
