#!/bin/sh
set -eu
compose() {
  docker compose --env-file /dev/null --project-name "$project_name" --file "$compose_file" "$@"
}
    curl --fail --silent --show-error "http://127.0.0.1:$auth_port/health/live" \
      >"$evidence_root/liveness.json"
    curl --fail --silent --show-error "http://127.0.0.1:$auth_port/health/ready" \
      >"$evidence_root/readiness.json"
    curl --fail --silent --show-error "http://127.0.0.1:$auth_port/api/auth/ok" \
      >"$evidence_root/auth-ok.json"
    grep -Fqx '{"status":"ok"}' "$evidence_root/liveness.json"
    grep -Fqx '{"status":"ready"}' "$evidence_root/readiness.json"
    grep -Fqx '{"ok":true}' "$evidence_root/auth-ok.json"
    test "$(compose exec -T auth id -u)" -ne 0
    test "$(compose exec -T auth node --version)" = v24.14.0
    compose exec -T auth test ! -e /app/auth/dist/$stale_canary_name

    curl --fail --silent --show-error \
      -H 'Cookie: cookie-canary=do-not-log' \
      "http://127.0.0.1:$auth_port/api/auth/ok?query-canary=do-not-log" \
      >"$evidence_root/auth-ok-canary.json"
    signup_status=$(curl --silent --show-error \
      --output "$evidence_root/signup-rejected.json" \
      --write-out '%{http_code}' \
      -H 'Content-Type: application/json' \
      -H 'Cookie: token-canary=do-not-log' \
      --data '{"email":"body-canary@example.test","password":"credential-canary-do-not-log"}' \
      "http://127.0.0.1:$auth_port/api/auth/sign-up/email")
    test "$signup_status" = 403
    compose logs --no-color auth auth-initialize >"$evidence_root/auth-services.log"

    if compose run --rm --no-deps -T --interactive=false \
      -e BETTER_AUTH_SECRET= \
      auth >"$evidence_root/invalid.stdout.log" 2>"$evidence_root/invalid.stderr.log"; then
      echo "Auth image accepted a missing BETTER_AUTH_SECRET" >&2
      exit 1
    fi
    grep -Fqx \
      '{"code":"AUTH_STARTUP_INVALID","event":"auth_startup_failed","reason":"CONFIGURATION_INVALID"}' \
      "$evidence_root/invalid.stderr.log"
    test ! -s "$evidence_root/invalid.stdout.log"

    mismatched_private_jwk='{"alg":"EdDSA","crv":"Ed25519","d":"ASCCVM_DYKEJvq18KV1M4UNFhxTHLKtdXxQFXLGlEBs","kid":"test-signing-key-01","kty":"OKP","use":"sig","x":"3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8"}'
    if compose run --rm --no-deps -T --interactive=false \
      -e THESISTRACE_MCP_SIGNING_PRIVATE_JWK="$mismatched_private_jwk" \
      auth >"$evidence_root/key-mismatch.stdout.log" \
      2>"$evidence_root/key-mismatch.stderr.log"; then
      echo "Auth image accepted a mismatched MCP signing key pair" >&2
      exit 1
    fi
    grep -Fqx \
      '{"code":"AUTH_STARTUP_INVALID","event":"auth_startup_failed","reason":"CONFIGURATION_INVALID"}' \
      "$evidence_root/key-mismatch.stderr.log"
    test ! -s "$evidence_root/key-mismatch.stdout.log"

    compose exec -T postgres psql \
      --username thesistrace_owner \
      --dbname thesistrace \
      --set ON_ERROR_STOP=1 \
      --command 'ALTER TABLE auth."session" ENABLE ROW LEVEL SECURITY' \
      >"$evidence_root/schema-drift-setup.log"
    if compose run --rm --no-deps -T --interactive=false \
      auth >"$evidence_root/drift.stdout.log" 2>"$evidence_root/drift.stderr.log"; then
      echo "Auth image accepted a row-security schema drift" >&2
      exit 1
    fi
    grep -Fqx \
      '{"code":"AUTH_STARTUP_INVALID","event":"auth_startup_failed","reason":"SCHEMA_CATALOG_DRIFT"}' \
      "$evidence_root/drift.stderr.log"
    test ! -s "$evidence_root/drift.stdout.log"
    if grep -R -E -q \
      'owner-test-password|auth-test-password|core-test-password|query-canary|cookie-canary|token-canary|body-canary|credential-canary' \
      "$evidence_root"; then
      echo "Auth image-smoke evidence exposed a credential" >&2
      exit 1
    fi
    if grep -R -F -q "$test_secret" "$evidence_root"; then
      echo "Auth image-smoke evidence exposed BETTER_AUTH_SECRET" >&2
      exit 1
    fi
