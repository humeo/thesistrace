#!/bin/sh
# Final-image assertions run in a dedicated process group owned by the Node test runner.
# TestRun supplies only its isolated project, mounts, fixture environment and evidence paths.
set -eu
compose() {
  if [ "$use_image_overlay" = true ]; then
    docker compose --env-file /dev/null --project-name "$project_name" --file "$base_file" --file "$test_file" --file "$image_smoke_file" "$@"
  else
    docker compose --env-file /dev/null --project-name "$project_name" --file "$base_file" --file "$test_file" "$@"
  fi
}
base_compose() {
  docker compose --env-file /dev/null --project-name "$project_name" --file "$base_file" "$@"
}
compose_run() { compose run --rm --no-deps -T --interactive=false "$@"; }
base_compose_run() { base_compose run --rm --no-deps -T --interactive=false "$@"; }
runtime_image_name() { printf '%s-%s\n' "$project_name" "$1"; }

verify_image_health() {
  suffix=$1
  compose_run \
    -e THESISTRACE_TEST_API_ORIGIN=http://api:8100 \
    -e THESISTRACE_TEST_WEB_ORIGIN=http://web:$caddy_port \
    -e THESISTRACE_TEST_SMOKE_STATE=/smoke-evidence/image-smoke-state.json \
    initialize python /smoke/tests/production_image_smoke.py health \
    >"$evidence_dir/health-$suffix.json" \
    2>"$evidence_dir/health-$suffix.stderr.log"
}

verify_caddy_single_origin() {
  expected_mcp_resource=$1
  curl --fail --silent --show-error --dump-header "$evidence_dir/caddy-security-headers.txt" \
    "$public_origin/data" \
    >"$evidence_dir/caddy-spa.html"
  curl --fail --silent --show-error "$public_origin/login" \
    >"$evidence_dir/caddy-spa-fallback.html"
  cmp "$evidence_dir/caddy-spa.html" "$evidence_dir/caddy-spa-fallback.html"
  curl --fail --silent --show-error "$public_origin/chat" \
    >"$evidence_dir/caddy-chat-spa-fallback.html"
  cmp "$evidence_dir/caddy-spa.html" "$evidence_dir/caddy-chat-spa-fallback.html"
  grep -Fi "Content-Security-Policy: default-src 'none'; script-src 'self';" \
    "$evidence_dir/caddy-security-headers.txt"
  grep -Fi "style-src 'self' 'unsafe-inline'; style-src-attr 'unsafe-inline'" \
    "$evidence_dir/caddy-security-headers.txt"
  grep -Fi "Referrer-Policy: no-referrer" \
    "$evidence_dir/caddy-security-headers.txt"
  grep -Fi "X-Content-Type-Options: nosniff" \
    "$evidence_dir/caddy-security-headers.txt"
  grep -Fi "Permissions-Policy:" "$evidence_dir/caddy-security-headers.txt"
  if grep -Fi "Strict-Transport-Security:" \
    "$evidence_dir/caddy-security-headers.txt"; then
    echo "Test Caddy unexpectedly emitted Production HSTS" >&2
    return 1
  fi
  curl --fail --silent --show-error "$public_origin/api/auth/ok" \
    >"$evidence_dir/caddy-auth.json"
  grep -Fqx '{"ok":true}' "$evidence_dir/caddy-auth.json"
  core_status=$(curl --silent --show-error \
    --output "$evidence_dir/caddy-core.json" --write-out '%{http_code}' \
    "$public_origin/api/data")
  test "$core_status" = 401
  agent_status=$(curl --silent --show-error \
    --header "Origin: $public_origin" \
    --output "$evidence_dir/caddy-agent.json" --write-out '%{http_code}' \
    "$public_origin/api/agent/models")
  test "$agent_status" = 401

  curl --fail --silent --show-error --max-time 10 \
    "$public_origin/.well-known/oauth-protected-resource/mcp" \
    >"$evidence_dir/caddy-mcp-metadata.json"
  grep -F "\"resource\":\"$expected_mcp_resource\"" \
    "$evidence_dir/caddy-mcp-metadata.json"
  mcp_unauthorized_status=$(curl --silent --show-error --max-time 10 \
    --header 'Content-Type: application/json' \
    --request POST --data '{}' \
    --output "$evidence_dir/caddy-mcp-unauthorized.json" \
    --write-out '%{http_code}' "$public_origin/mcp")
  test "$mcp_unauthorized_status" = 401
  mcp_query_token_status=$(curl --silent --show-error --max-time 10 \
    --header 'Authorization: Bearer caddy-query-token-canary' \
    --header 'Content-Type: application/json' \
    --request POST --data '{}' \
    --output /dev/null --write-out '%{http_code}' \
    "$public_origin/mcp?access_token=caddy-query-token-canary")
  test "$mcp_query_token_status" = 400
  mcp_arbitrary_query_status=$(curl --silent --show-error --max-time 10 \
    --header 'Content-Type: application/json' \
    --request POST --data '{}' \
    --output /dev/null --write-out '%{http_code}' \
    "$public_origin/mcp?probe=caddy-query-canary")
  test "$mcp_arbitrary_query_status" = 400
  mcp_metadata_query_status=$(curl --silent --show-error --max-time 10 \
    --output /dev/null --write-out '%{http_code}' \
    "$public_origin/.well-known/oauth-protected-resource/mcp?probe=caddy-query-canary")
  test "$mcp_metadata_query_status" = 400
  for noncanonical_mcp_path in \
    /mcp/ /mcp/sse /.well-known/oauth-protected-resource/mcp/; do
    noncanonical_mcp_status=$(curl --silent --show-error --max-time 10 \
      --output /dev/null --write-out '%{http_code}' \
      "$public_origin$noncanonical_mcp_path")
    test "$noncanonical_mcp_status" = 404
  done

  auth_canary_status=$(curl --silent --show-error \
    --header "Origin: $public_origin" \
    --header 'Content-Type: application/json' \
    --header 'Cookie: observability=observability-request-canary' \
    --request POST \
    --data '{"email":"observability-request-canary@example.test","otp":"000000"}' \
    --output /dev/null --write-out '%{http_code}' \
    "$public_origin/api/auth/sign-in/email-otp?token=observability-request-canary")
  test "$auth_canary_status" = 400 || test "$auth_canary_status" = 401

  for private_path in \
    /health/live /health/ready \
    /internal/session/verify /internal/session/exchange; do
    private_status=$(curl --silent --show-error \
      --output /dev/null --write-out '%{http_code}' \
      "$public_origin$private_path")
    test "$private_status" = 404
  done
}

verify_caddy_backend_independence() {
  compose stop auth api >/dev/null
  curl --fail --silent --show-error "$public_origin/data" \
    >"$evidence_dir/caddy-backends-unavailable.html"
  auth_status=$(curl --silent --show-error \
    --header 'Authorization: Bearer observability-outage-canary' \
    --header 'Cookie: session=observability-outage-canary' \
    --output /dev/null --write-out '%{http_code}' \
    "$public_origin/api/auth/ok?token=observability-outage-canary")
  core_status=$(curl --silent --show-error \
    --output /dev/null --write-out '%{http_code}' "$public_origin/api/data")
  test "$auth_status" = 502
  test "$core_status" = 502
  compose up --detach --no-build --wait --wait-timeout 120 auth api
  verify_caddy_single_origin "$1"
}

run_mcp_image_smoke() {
  phase=$1
  compose_run \
    -e THESISTRACE_MCP_ALLOWED_HOSTS="$mcp_allowed_hosts" \
    -e THESISTRACE_MCP_ALLOWED_ORIGINS="$mcp_allowed_origins" \
    -e THESISTRACE_TEST_API_ORIGIN=http://api:8100 \
    -e THESISTRACE_TEST_EVIDENCE_DIR=/smoke-evidence \
    -e THESISTRACE_TEST_IMAGE_ID="$image_revision" \
    -e THESISTRACE_TEST_RANDOM_SEED=1401 \
    initialize python /smoke/tests/production_mcp_image_smoke.py "$phase"
}

capture_stopped_api_state() {
  container_id=$(compose ps --all --quiet api)
  test -n "$container_id" || return 1
  docker inspect --format \
    '{"status":"{{.State.Status}}","exit_code":{{.State.ExitCode}},"oom_killed":{{.State.OOMKilled}}}' \
    "$container_id" >"$evidence_dir/mcp-api-stopped.json"
}

verify_service_readiness_outage() {
  service=$1
  dependency=$2
  outage_status=0
  recovery_status=0
  compose stop "$service" >/dev/null
  compose_run \
    -e THESISTRACE_TEST_API_ORIGIN=http://api:8100 \
    -e THESISTRACE_TEST_WEB_ORIGIN=http://web:$caddy_port \
    -e THESISTRACE_TEST_SMOKE_STATE=/smoke-evidence/image-smoke-state.json \
    -e THESISTRACE_TEST_UNAVAILABLE_DEPENDENCY="$dependency" \
    initialize python /smoke/tests/production_image_smoke.py readiness-outage \
    >"$evidence_dir/readiness-$dependency-unavailable.json" \
    2>"$evidence_dir/readiness-$dependency-unavailable.stderr.log" \
    || outage_status=$?
  compose logs --no-color "$service" \
    >"$evidence_dir/stopped-$service.log" 2>&1 || true
  test -s "$evidence_dir/stopped-$service.log" || outage_status=1
  compose up --detach --no-build --wait --wait-timeout 120 "$service" \
    || recovery_status=$?
  if [ "$recovery_status" -eq 0 ]; then
    verify_image_health "$dependency-recovered" || recovery_status=$?
  fi
  if [ "$outage_status" -ne 0 ]; then
    return "$outage_status"
  fi
  return "$recovery_status"
}

verify_dataset_readiness_outage() {
  outage_container="dataset-store-outage-$run_id"
  outage_parent="$run_root/dataset-store-outage"
  outage_root="$outage_parent/current"
  outage_status=0
  recovery_status=0
  mkdir -p "$outage_parent"
  ln -s ../canonical-data "$outage_root"
  compose_run --detach \
    --name "$outage_container" \
    --volume "$outage_parent:/smoke-data/dataset-store-outage:ro" \
    -e THESISTRACE_DATA_MOUNT=/smoke-data/dataset-store-outage/current \
    api >/dev/null || outage_status=$?
  if [ "$outage_status" -eq 0 ]; then
    compose_run \
      -e THESISTRACE_TEST_API_ORIGIN="http://$outage_container:8100" \
      -e THESISTRACE_TEST_WEB_ORIGIN=http://web:$caddy_port \
      -e THESISTRACE_TEST_SMOKE_STATE=/smoke-evidence/image-smoke-state.json \
      initialize python /smoke/tests/production_image_smoke.py health \
      >"$evidence_dir/readiness-dataset_store-before-outage.json" \
      2>"$evidence_dir/readiness-dataset_store-before-outage.stderr.log" \
      || outage_status=$?
  fi
  if [ "$outage_status" -eq 0 ]; then
    unlink "$outage_root" || outage_status=$?
  fi
  if [ "$outage_status" -eq 0 ]; then
    compose_run \
      -e THESISTRACE_TEST_API_ORIGIN="http://$outage_container:8100" \
      -e THESISTRACE_TEST_WEB_ORIGIN=http://web:$caddy_port \
      -e THESISTRACE_TEST_SMOKE_STATE=/smoke-evidence/image-smoke-state.json \
      -e THESISTRACE_TEST_UNAVAILABLE_DEPENDENCY=dataset_store \
      initialize python /smoke/tests/production_image_smoke.py readiness-outage \
      >"$evidence_dir/readiness-dataset_store-unavailable.json" \
      2>"$evidence_dir/readiness-dataset_store-unavailable.stderr.log" \
      || outage_status=$?
  fi
  docker logs "$outage_container" \
    >"$evidence_dir/readiness-dataset_store-api.log" 2>&1 || true
  docker stop "$outage_container" >/dev/null || recovery_status=$?
  if [ "$recovery_status" -eq 0 ]; then
    verify_image_health dataset_store-recovered || recovery_status=$?
  fi
  if [ "$outage_status" -ne 0 ]; then
    return "$outage_status"
  fi
  return "$recovery_status"
}

verify_worker_capacity_rejection() {
  for role in research batch-research tracking; do
    if [ "$role" = batch-research ]; then
      service=batch-research-worker
    else
      service="${role}-worker"
    fi
    stdout="$evidence_dir/${role}-worker-cpu-capacity.stdout.log"
    stderr="$evidence_dir/${role}-worker-cpu-capacity.stderr.log"
    if compose_run "$service" \
      thesistrace-core-worker --role "$role" --once --cpu-count 3 \
      >"$stdout" 2>"$stderr"; then
      echo "$role Worker accepted a CPU declaration above its cgroup limit" >&2
      return 1
    fi
    grep -F '"event":"worker_startup_failed"' "$stderr" >/dev/null
    grep -F '"failure_code":"WORKER_CAPACITY_INVALID"' "$stderr" >/dev/null

    stdout="$evidence_dir/${role}-worker-memory-capacity.stdout.log"
    stderr="$evidence_dir/${role}-worker-memory-capacity.stderr.log"
    if compose_run "$service" \
      thesistrace-core-worker --role "$role" --once \
      --memory-bytes 3221225472 \
      >"$stdout" 2>"$stderr"; then
      echo "$role Worker accepted a memory declaration above its cgroup limit" >&2
      return 1
    fi
    grep -F '"event":"worker_startup_failed"' "$stderr" >/dev/null
    grep -F '"failure_code":"WORKER_CAPACITY_INVALID"' "$stderr" >/dev/null
  done
}

verify_tushare_secret_scope() {
  for service in \
    postgres rustfs initialize auth-initialize auth api research-worker \
    batch-research-worker tracking-worker web; do
    container_id="$project_name-$service-1"
    container_environment=$(docker inspect \
      --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id") \
      || return 1
    if printf '%s\n' "$container_environment" \
      | grep -q '^THESISTRACE_TUSHARE_TOKEN='; then
      echo "Tushare Secret escaped into $service" >&2
      return 1
    fi
  done
  worker_id="$project_name-data-operator-worker-1"
  worker_environment=$(docker inspect \
    --format '{{range .Config.Env}}{{println .}}{{end}}' "$worker_id") \
    || return 1
  printf '%s\n' "$worker_environment" \
    | grep -q '^THESISTRACE_TUSHARE_TOKEN=' \
    || return 1
  browser_html=$(curl --fail --silent --show-error "$public_origin/data") \
    || return 1
  if printf '%s' "$browser_html" | grep -Fq "$tushare_test_token"; then
    echo "Tushare Secret escaped into browser state" >&2
    return 1
  fi
}

verify_data_operator_worker_secret_rejection() {
  for scenario in missing placeholder; do
    case "$scenario" in
      missing) token= ;;
      placeholder) token=placeholder-image-smoke-token ;;
    esac
    stdout="$evidence_dir/data-operator-worker-$scenario-token.stdout.json"
    stderr="$evidence_dir/data-operator-worker-$scenario-token.stderr.log"
    if compose_run \
      -e "THESISTRACE_TUSHARE_TOKEN=$token" \
      data-operator-worker thesistrace-data-operator worker \
      >"$stdout" 2>"$stderr"; then
      echo "Data Operator Worker accepted a $scenario Tushare credential" >&2
      return 1
    fi
    if ! grep -E '"code"[[:space:]]*:[[:space:]]*"WORKER_TUSHARE_TOKEN_INVALID"' \
      "$stdout" "$stderr" >/dev/null; then
      echo "Data Operator Worker did not report the $scenario credential failure" >&2
      return 1
    fi
  done
  verify_image_health data-operator-secret-rejected
}

verify_single_data_operator_worker() {
  worker_ids=$(compose ps --status running --quiet data-operator-worker)
  worker_count=$(printf '%s\n' "$worker_ids" | sed '/^$/d' | wc -l | tr -d ' ')
  test "$worker_count" = 1 || {
    echo "expected exactly one running Data Operator Worker, found $worker_count" >&2
    return 1
  }
  worker_id=$(printf '%s\n' "$worker_ids" | sed -n '1p')
  docker inspect --format '{{json .Config.Cmd}}' "$worker_id" \
    >"$evidence_dir/data-operator-worker-command.json"
  grep -F 'thesistrace-data-operator' \
    "$evidence_dir/data-operator-worker-command.json" >/dev/null
  grep -F 'worker' "$evidence_dir/data-operator-worker-command.json" >/dev/null
  if grep -F -- '--once' "$evidence_dir/data-operator-worker-command.json" >/dev/null; then
    echo "Production Data Operator Worker is running as a one-shot command" >&2
    return 1
  fi
}

verify_research_child_cgroup_oom_detection() {
  backend_image=$(runtime_image_name initialize)
  output="$evidence_dir/research-child-cgroup-oom.json"
  docker run --rm \
    --memory 201326592 \
    --memory-swap 201326592 \
    --entrypoint python \
    "$backend_image" -c '
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from thesistrace.research_run.execution import (
    ResearchExecutionResourceExhausted,
    SupervisedResearchExecution,
)
from thesistrace.research_run.supervised_child import SupervisedChildTransport

def oom_kill_count():
    for path in (
        Path("/sys/fs/cgroup/memory.events.local"),
        Path("/sys/fs/cgroup/memory.events"),
    ):
        if not path.exists():
            continue
        values = dict(line.split(maxsplit=1) for line in path.read_text().splitlines())
        if "oom_kill" in values:
            return int(values["oom_kill"])
    return None

before = oom_kill_count()
if before is None:
    raise SystemExit("cgroup v2 oom_kill evidence is unavailable")
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "values=[]\nwhile True: values.append(bytearray(16 * 1024 * 1024))",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
events = []
execution = SupervisedResearchExecution(
    SupervisedChildTransport(child, before),
    SimpleNamespace(
        run_id="image-smoke-oom",
        attempt_id="attempt-1",
        immutable_input=SimpleNamespace(research_kind="factor_evaluation"),
    ),
    {"final": False},
    events.append,
    1536 * 1024 * 1024,
)
classified = False
try:
    execution.advance(cancel_requested=lambda: False)
except ResearchExecutionResourceExhausted:
    classified = True
finally:
    execution.close()
after = oom_kill_count()
if not classified:
    raise SystemExit(
        f"child OOM was not classified: returncode={child.returncode}, "
        f"before={before}, after={after}"
    )
if child.poll() is None:
    raise SystemExit("OOM child was not reaped by the production supervisor")
if not any(event["event"] == "research_execution_child_exited" for event in events):
    raise SystemExit("production supervisor emitted no child-exit evidence")
print(json.dumps({
    "after_oom_kill": after,
    "before_oom_kill": before,
    "classified": True,
    "child_returncode": child.returncode,
    "child_exit_emitted": True,
}, sort_keys=True, separators=(",", ":")))
' >"$output"
  grep -F '"classified":true' "$output" >/dev/null
  grep -F '"child_returncode":-9' "$output" >/dev/null
}

case "${1:-}" in
  verify_image_health | verify_caddy_single_origin | verify_caddy_backend_independence | run_mcp_image_smoke | capture_stopped_api_state | verify_service_readiness_outage | verify_dataset_readiness_outage | verify_worker_capacity_rejection | verify_tushare_secret_scope | verify_data_operator_worker_secret_rejection | verify_single_data_operator_worker | verify_research_child_cgroup_oom_detection) "$@" ;;
  *) echo "unknown final-image check" >&2; exit 2 ;;
esac
