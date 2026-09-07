#!/bin/sh
set -eu
compose() {
  docker compose --env-file /dev/null --project-name "$project_name" --file "$compose_file" "$@"
}
    curl --fail --silent --show-error --max-time 10 \
      "http://127.0.0.1:$agent_port/health/live" \
      >"$evidence_root/liveness.json"
    curl --fail --silent --show-error --max-time 10 \
      "http://127.0.0.1:$agent_port/health/ready" \
      >"$evidence_root/readiness.json"
    grep -Fqx '{"status":"ok"}' "$evidence_root/liveness.json"
    grep -Fqx '{"status":"ready"}' "$evidence_root/readiness.json"
    test "$(compose exec -T agent id -u)" -ne 0
    test "$(compose exec -T agent node --version)" = v24.14.0
    compose exec -T agent test ! -e /app/agent/dist/$stale_canary_name

    unauthenticated_status=$(curl --silent --show-error --max-time 10 \
      --output "$evidence_root/unauthenticated.json" \
      --write-out '%{http_code}' \
      -H 'Origin: https://thesistrace.test' \
      "http://127.0.0.1:$agent_port/api/agent/models")
    test "$unauthenticated_status" = 401
    grep -Fqx '{"code":"AUTHENTICATION_REQUIRED"}' "$evidence_root/unauthenticated.json"

    curl --fail --silent --show-error --max-time 10 \
      -H 'Content-Type: application/json' \
      -H 'Cookie: thesistrace.session_token=image-smoke-session' \
      -H 'Origin: https://thesistrace.test' \
      --data '{"threadId":"00000000-0000-4000-8000-000000000201","runId":"00000000-0000-4000-8000-000000000301","messages":[{"id":"00000000-0000-4000-8000-000000000401","role":"user","content":"Inspect the available research context."}],"state":{},"tools":[],"context":[],"forwardedProps":{"thesistrace":{"command":"prompt","modelKey":"gpt-5.6-luna","reasoningEffort":"max","sessionMode":"new"}}}' \
      "http://127.0.0.1:$agent_port/api/agent/copilotkit/agent/research/run" \
      >"$evidence_root/run.sse"
    grep -F '"type":"RUN_STARTED"' "$evidence_root/run.sse" >/dev/null
    grep -F '"type":"TOOL_CALL_START"' "$evidence_root/run.sse" >/dev/null
    grep -F '"toolCallName":"get_research_context"' "$evidence_root/run.sse" >/dev/null
    node "$agent_root/scripts/assert-safe-tool-sse.mjs" "$evidence_root/run.sse"
    grep -F '"type":"TEXT_MESSAGE_CONTENT"' "$evidence_root/run.sse" >/dev/null
    grep -F '"type":"RUN_FINISHED"' "$evidence_root/run.sse" >/dev/null
    test "$(grep -F -c '"delta":"{}"' "$evidence_root/run.sse")" -eq 1
    if grep -F 'image-smoke-private-mcp-result' "$evidence_root/run.sse"; then
      echo "Agent image smoke exposed a raw MCP result" >&2
      exit 1
    fi
    compose exec -T postgres psql \
      --username thesistrace_owner \
      --dbname thesistrace \
      --tuples-only \
      --no-align \
      --command "SELECT status || '|' || (token_usage->'outputTokens'->>'total') FROM agent.agent_run WHERE id='00000000-0000-4000-8000-000000000301'" \
      >"$evidence_root/run-row.txt"
    grep -Fqx 'completed|24' "$evidence_root/run-row.txt"

    if compose run --rm --no-deps -T --interactive=false \
      -e THESISTRACE_AGENT_OPENAI_API_KEY= \
      agent >"$evidence_root/invalid.stdout.log" 2>"$evidence_root/invalid.stderr.log"; then
      echo "Agent image accepted a missing OpenAI model credential" >&2
      exit 1
    fi
    grep -Fqx \
      '{"code":"AGENT_STARTUP_INVALID","event":"agent_startup_failed"}' \
      "$evidence_root/invalid.stderr.log"
    test ! -s "$evidence_root/invalid.stdout.log"

    compose exec -T postgres psql \
      --username thesistrace_owner \
      --dbname thesistrace \
      --set ON_ERROR_STOP=1 \
      --command 'ALTER TABLE agent.chat_session ENABLE ROW LEVEL SECURITY' \
      >"$evidence_root/schema-drift-setup.log"
    if compose run --rm --no-deps -T --interactive=false \
      agent >"$evidence_root/drift.stdout.log" 2>"$evidence_root/drift.stderr.log"; then
      echo "Agent image accepted Agent schema drift" >&2
      exit 1
    fi
    grep -Fqx \
      '{"code":"AGENT_STARTUP_INVALID","event":"agent_startup_failed"}' \
      "$evidence_root/drift.stderr.log"
    test ! -s "$evidence_root/drift.stdout.log"

    if grep -R -E -q \
      'owner-test-password|agent-test-password|auth-test-password|core-test-password|thesistrace.session_token=image-smoke-session|integration-secret' \
      "$evidence_root"; then
      echo "Agent image-smoke evidence exposed a credential" >&2
      exit 1
    fi
    if grep -R -F -q "$openai_secret" "$evidence_root"; then
      echo "Agent image-smoke evidence exposed the provider secret" >&2
      exit 1
    fi
