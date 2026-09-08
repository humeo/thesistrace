#!/bin/sh
set -eu
case "$1" in
  routing)
docker exec "$container_name" wget --quiet --no-check-certificate \
  --output-document - https://thesistrace.test/login \
  >"$evidence_root/spa.html"
if docker exec "$client_one_name" wget --quiet --no-check-certificate \
  --output-document /dev/null \
  https://thesistrace.test/operator/researchers; then
  echo "Caddy exposed the Operator page without Auth admission" >&2
  exit 1
fi
docker exec "$client_one_name" wget --server-response --no-check-certificate \
  --output-document /dev/null \
  https://thesistrace.test/operator/researchers \
  >"$evidence_root/operator-denied.stdout.log" \
  2>"$evidence_root/operator-denied.stderr.log" || true
grep -F "404 Not Found" "$evidence_root/operator-denied.stderr.log"
docker exec "$client_one_name" wget --quiet --no-check-certificate \
  --header 'Cookie: session=operator-allowed' \
  --output-document - \
  https://thesistrace.test/operator/researchers \
  >"$evidence_root/operator-spa.html"
cmp "$evidence_root/spa.html" "$evidence_root/operator-spa.html"
docker exec "$container_name" wget --server-response --spider \
  --no-check-certificate \
  http://thesistrace.test/ \
  >"$evidence_root/http-redirect.stdout.log" \
  2>"$evidence_root/http-redirect.stderr.log"
grep -F "308 Permanent Redirect" "$evidence_root/http-redirect.stderr.log"
grep -F "Location: https://thesistrace.test/" \
  "$evidence_root/http-redirect.stderr.log"

client_ip_one=$(docker exec "$client_one_name" wget --quiet \
  --no-check-certificate --output-document - \
  https://thesistrace.test/api/auth/client-ip)
client_ip_two=$(docker exec "$client_two_name" wget --quiet \
  --no-check-certificate --output-document - \
  https://thesistrace.test/api/auth/client-ip)
forged_client_ip=$(docker exec "$client_one_name" wget --quiet \
  --header 'X-ThesisTrace-Client-IP: 203.0.113.250' \
  --no-check-certificate --output-document - \
  https://thesistrace.test/api/auth/client-ip)
test -n "$client_ip_one"
test -n "$client_ip_two"
test "$client_ip_one" != "$client_ip_two"
test "$forged_client_ip" = "$client_ip_one"

# Only the explicitly trusted edge may supply the visitor address.
for visitor in 203.0.113.10 203.0.113.11; do
  forwarded=$(docker exec "$client_one_name" wget --quiet \
    --header "CF-Connecting-IP: $visitor" \
    --header 'X-Forwarded-For: 203.0.113.250' \
    --header 'X-ThesisTrace-Client-IP: 203.0.113.251' \
    --no-check-certificate --output-document - \
    https://thesistrace.test/api/auth/client-ip)
  test "$forwarded" = "$visitor"
done
untrusted=$(docker exec "$client_two_name" wget --quiet \
  --header 'CF-Connecting-IP: 203.0.113.10' \
  --no-check-certificate --output-document - \
  https://thesistrace.test/api/auth/client-ip)
test "$untrusted" = "$client_ip_two"

for private_probe in \
  "health/live private-health" \
  "internal/session/verify private-internal"; do
  set -- $private_probe
  private_path=$1
  evidence_name=$2
  if docker exec "$container_name" wget --quiet --no-check-certificate \
    --output-document /dev/null "https://thesistrace.test/$private_path"; then
    echo "Caddy exposed private path /$private_path" >&2
    exit 1
  fi
  docker exec "$container_name" wget --server-response --no-check-certificate \
    --output-document /dev/null "https://thesistrace.test/$private_path" \
    >"$evidence_root/$evidence_name.stdout.log" \
    2>"$evidence_root/$evidence_name.stderr.log" || true
  grep -F "404 Not Found" "$evidence_root/$evidence_name.stderr.log"
done

    ;;
  security)
docker exec "$container_name" wget --server-response --spider \
  --no-check-certificate https://thesistrace.test/login \
  >"$evidence_root/security-headers.stdout.log" \
  2>"$evidence_root/security-headers.stderr.log"
security_headers="$evidence_root/security-headers.stderr.log"
grep -Fi "Content-Security-Policy: default-src 'none'; script-src 'self';" \
  "$security_headers"
grep -Fi "style-src 'self' 'unsafe-inline'; style-src-attr 'unsafe-inline'" \
  "$security_headers"
grep -Fi "Referrer-Policy: no-referrer" "$security_headers"
grep -Fi "X-Content-Type-Options: nosniff" "$security_headers"
grep -Fi "X-Frame-Options: DENY" "$security_headers"
grep -Fi "Permissions-Policy:" "$security_headers"
grep -Fi "Strict-Transport-Security: max-age=31536000" "$security_headers"
grep -Ei "X-Request-Id: [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" \
  "$security_headers"
if grep -Ei "Strict-Transport-Security:.*(includeSubDomains|preload)" \
  "$security_headers"; then
  echo "Caddy emitted an unapproved HSTS directive" >&2
  exit 1
fi

forged_request_id=$(docker exec "$client_one_name" wget --quiet \
  --header 'X-Request-ID: request-canary-forged-id' \
  --no-check-certificate --output-document - \
  https://thesistrace.test/api/auth/request-id)
test "$forged_request_id" != request-canary-forged-id
printf '%s\n' "$forged_request_id" \
  | grep -Eq '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

docker exec "$client_one_name" wget --quiet \
  --header 'Authorization: Bearer request-canary-authorization' \
  --header 'Cookie: session=request-canary-cookie' \
  --no-check-certificate --output-document /dev/null \
  'https://thesistrace.test/api/auth/request-canary-path?token=request-canary-query'
docker stop "$auth_container_name" >/dev/null
if docker exec "$client_one_name" wget --quiet \
  --header 'Authorization: Bearer request-canary-outage-authorization' \
  --header 'Cookie: session=request-canary-outage-cookie' \
  --no-check-certificate --output-document /dev/null \
  'https://thesistrace.test/api/auth/client-ip?token=request-canary-outage-query'; then
  echo "Caddy reached a stopped Auth backend" >&2
  exit 1
fi
attempt=0
until docker logs "$container_name" 2>&1 \
  | grep -F '"logger":"http.log.error.log0"' >/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ]; then
    echo "Caddy sanitized access log did not become visible" >&2
    exit 1
  fi
  sleep 0.1
done
docker logs "$container_name" >"$evidence_root/caddy-sanitized.log" 2>&1
if grep -F 'request-canary' "$evidence_root/caddy-sanitized.log"; then
  echo "Caddy access log exposed a request canary" >&2
  exit 1
fi
access_logs=$(grep -F 'http.log.access' "$evidence_root/caddy-sanitized.log")
test -n "$access_logs"
printf '%s\n' "$access_logs" | grep -F '"request_id":' >/dev/null
printf '%s\n' "$access_logs" | grep -F '"method":' >/dev/null
printf '%s\n' "$access_logs" | grep -F '"path":' >/dev/null
printf '%s\n' "$access_logs" | grep -F '"status":' >/dev/null
printf '%s\n' "$access_logs" | grep -F '"duration":' >/dev/null
if printf '%s\n' "$access_logs" \
  | grep -E '"(request|uuid|resp_headers|bytes_read|user_id|size)":'; then
  echo "Caddy access log retained an unapproved field" >&2
  exit 1
fi
if grep -E '"(request|headers|uri|query|body|token|formula|object_key|manifest|resp_headers|err_trace)":' \
  "$evidence_root/caddy-sanitized.log"; then
  echo "Caddy runtime log retained an unapproved field" >&2
  exit 1
fi

    ;;
  *) exit 2 ;;
esac
