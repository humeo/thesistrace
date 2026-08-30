from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "core"


def _service(source: str, name: str, next_name: str | None = None) -> str:
    section = source.split(f"\n  {name}:\n", maxsplit=1)[1]
    if next_name is not None:
        section = section.split(f"\n  {next_name}:\n", maxsplit=1)[0]
    return section


def test_caddy_is_the_only_web_runtime_and_preserves_api_paths() -> None:
    dockerfile = (DEPLOY / "Dockerfile.web").read_text()
    caddyfile = (DEPLOY / "Caddyfile").read_text()

    assert (
        "FROM caddy:2.11.4-alpine@sha256:"
        "5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648"
        in dockerfile
    )
    assert "nginx" not in dockerfile.lower()
    assert "COPY --from=build /app/web/dist /srv" in dockerfile
    assert "caddy validate --config /etc/caddy/Caddyfile" in dockerfile
    assert not (DEPLOY / "nginx.conf.template").exists()

    private = caddyfile.index("handle @private_backend")
    mcp_query = caddyfile.index("handle @mcp_query")
    mcp_noncanonical = caddyfile.index("handle @mcp_noncanonical")
    mcp = caddyfile.index("handle /mcp {")
    mcp_metadata = caddyfile.index(
        "handle /.well-known/oauth-protected-resource/mcp"
    )
    auth = caddyfile.index("handle /api/auth/*")
    agent = caddyfile.index("handle /api/agent/*")
    core = caddyfile.index("handle /api/*")
    hashed = caddyfile.index("handle @hashed_assets")
    fallback = caddyfile.rindex("handle {")
    assert (
        private
        < mcp_query
        < mcp_noncanonical
        < mcp
        < mcp_metadata
        < auth
        < agent
        < core
        < hashed
        < fallback
    )
    assert "handle_path" not in caddyfile
    assert "reverse_proxy auth:8200" in caddyfile
    assert "reverse_proxy agent:8400" in caddyfile
    assert "reverse_proxy api:8100" in caddyfile
    assert caddyfile.count("reverse_proxy api:8100") == 3
    assert caddyfile.count(
        "header_up X-ThesisTrace-Client-IP {remote_host}"
    ) == 5
    assert caddyfile.count("header_up X-Request-ID {http.request.uuid}") == 5
    assert ">X-Request-ID {http.request.uuid}" in caddyfile
    assert "path /health /health/* /internal /internal/*" in caddyfile
    assert "path /mcp /.well-known/oauth-protected-resource/mcp" in caddyfile
    assert 'not query ""' in caddyfile
    assert "path /mcp/* /.well-known/oauth-protected-resource/mcp/*" in caddyfile
    assert 'respond 404' in caddyfile
    assert 'Cache-Control "no-store"' in caddyfile
    assert 'Cache-Control "public, max-age=31536000, immutable"' in caddyfile
    assert "try_files {path} /index.html" in caddyfile
    assert "{$THESISTRACE_PUBLIC_ORIGIN}" in caddyfile
    assert "{$THESISTRACE_CADDY_TLS_DIRECTIVE}" in caddyfile
    assert "auto_https off" not in caddyfile
    assert "tls internal" not in caddyfile


def test_caddy_discards_idle_upstream_connections_before_app_servers_do() -> None:
    caddyfile = (DEPLOY / "Caddyfile").read_text()

    # Uvicorn and the Node HTTP servers close idle HTTP/1.1 connections after 5s.
    # Caddy must retire its pooled connections first or a non-idempotent request can
    # receive a 502 while writing to an upstream socket that has just been closed.
    assert caddyfile.count("transport http {") == 5
    assert caddyfile.count("keepalive 2s") == 5


def test_caddy_applies_the_exact_security_and_sanitized_logging_contract() -> None:
    caddyfile = (DEPLOY / "Caddyfile").read_text()

    assert (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "style-src-attr 'unsafe-inline'; connect-src 'self'; "
        "form-action 'self'; img-src 'self' data:; font-src 'self'; "
        "base-uri 'none'; object-src 'none'; frame-src 'none'; "
        "frame-ancestors 'none'"
    ) in caddyfile
    assert ">Referrer-Policy \"no-referrer\"" in caddyfile
    assert ">X-Content-Type-Options \"nosniff\"" in caddyfile
    assert ">X-Frame-Options \"DENY\"" in caddyfile
    assert ">Permissions-Policy" in caddyfile
    assert "{$THESISTRACE_CADDY_HSTS_DIRECTIVE}" in caddyfile
    assert "includeSubDomains" not in caddyfile
    assert "preload" not in caddyfile

    for forbidden_field in (
        "request delete",
        "uuid delete",
        "bytes_read delete",
        "user_id delete",
        "size delete",
        "resp_headers delete",
        "err_id delete",
        "err_trace delete",
    ):
        assert forbidden_field in caddyfile
    assert "log_append request_id {http.request.uuid}" in caddyfile
    assert "log_append method {http.request.method}" in caddyfile
    assert "log_append path {http.request.uri.path}" not in caddyfile
    for normalized_path in (
        "/private/*",
        "/mcp",
        "/mcp/*",
        "/.well-known/oauth-protected-resource/mcp",
        "/api/auth/*",
        "/api/agent/*",
        "/api/*",
        "/assets/*",
        "/*",
    ):
        assert f"log_append path {normalized_path}" in caddyfile
    assert "http.request.body" not in caddyfile
    assert "http.response.body" not in caddyfile
    assert "http.request.uri.query" not in caddyfile
    assert "log default" in caddyfile
    for runtime_field in (
        "request",
        "headers",
        "uri",
        "query",
        "body",
        "token",
        "formula",
        "object_key",
        "manifest",
        "resp_headers",
        "err_trace",
    ):
        assert f"{runtime_field} delete" in caddyfile


def test_auth_image_reuses_the_package_store_for_production_deploy() -> None:
    dockerfile = (DEPLOY / "Dockerfile.auth").read_text()

    assert dockerfile.count(
        "--mount=type=cache,target=/root/.local/share/pnpm/store"
    ) == 2
    assert "pnpm --filter thesistrace-auth deploy --prod /auth-runtime" in dockerfile


def test_agent_image_is_a_private_pinned_node_runtime() -> None:
    dockerfile = (DEPLOY / "Dockerfile.agent").read_text()

    assert dockerfile.count("node:24.14.0-bookworm-slim@sha256:") == 2
    assert dockerfile.count(
        "--mount=type=cache,target=/root/.local/share/pnpm/store"
    ) == 2
    assert "pnpm --filter thesistrace-agent-host deploy --prod /agent-runtime" in dockerfile
    assert "USER node" in dockerfile


def test_base_compose_has_independent_agent_auth_and_core_identities() -> None:
    compose = (DEPLOY / "compose.yaml").read_text()
    core_environment = compose.split("x-core-environment:", 1)[1].split(
        "\nx-backend:", 1
    )[0]

    for service in ("auth-initialize", "auth", "agent-initialize", "agent", "web"):
        assert f"  {service}:\n" in compose
    assert "POSTGRES_USER: thesistrace_owner" in compose
    assert "010-runtime-roles.sh:/docker-entrypoint-initdb.d/010-runtime-roles.sh:ro" in compose
    assert "postgresql://core_runtime:" in compose
    assert "postgresql://auth_runtime:" in compose
    assert "postgresql://thesistrace_owner:" in compose
    assert "THESISTRACE_PUBLIC_ORIGIN: ${THESISTRACE_PUBLIC_ORIGIN" in compose
    assert "THESISTRACE_ENVIRONMENT: ${THESISTRACE_ENVIRONMENT" in compose
    assert "THESISTRACE_ENVIRONMENT: ${THESISTRACE_ENVIRONMENT" in core_environment
    assert "BETTER_AUTH_SECRET: ${BETTER_AUTH_SECRET" in compose
    assert "    ports:\n" not in compose

    auth_initializer = _service(compose, "auth-initialize", "auth")
    auth = _service(compose, "auth", "agent")
    agent = _service(compose, "agent", "agent-initialize")
    agent_initializer = _service(compose, "agent-initialize", "initialize")
    api = _service(compose, "api", "research-worker")
    research_worker = _service(
        compose, "research-worker", "batch-research-worker"
    )
    batch_worker = _service(
        compose, "batch-research-worker", "tracking-worker"
    )
    tracking_worker = _service(compose, "tracking-worker", "web")
    web = _service(compose, "web")
    assert "THESISTRACE_OWNER_DATABASE_URL" in auth_initializer
    assert "condition: service_healthy" in auth_initializer
    assert "THESISTRACE_AUTH_DATABASE_URL" in auth
    assert "THESISTRACE_MCP_SIGNING_PRIVATE_JWK" in auth
    assert "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK" in auth
    assert "THESISTRACE_MCP_AGENT_SCOPES" in auth
    assert "THESISTRACE_AUTH_INTERNAL_ORIGIN: http://auth:8200" in agent
    assert "THESISTRACE_MCP_INTERNAL_URL: http://api:8100/mcp" in agent
    assert "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS" in agent
    assert "THESISTRACE_MCP_CLOCK_SKEW_SECONDS" in agent
    assert "THESISTRACE_MCP_SIGNING_PRIVATE_JWK" not in agent
    assert "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK" not in agent
    assert "THESISTRACE_MCP_AGENT_SCOPES" not in agent
    assert "THESISTRACE_AGENT_MODEL_REGISTRY" in agent
    assert "image: ${THESISTRACE_AGENT_IMAGE:" in compose
    assert "postgresql://agent_runtime:" in agent
    assert "THESISTRACE_DATABASE_URL" not in agent
    assert "THESISTRACE_AUTH_DATABASE_URL" not in agent
    assert "THESISTRACE_S3_" not in agent
    assert "    ports:\n" not in agent
    assert "THESISTRACE_OWNER_DATABASE_URL" in agent_initializer
    assert "THESISTRACE_AGENT_DATABASE_URL" not in agent_initializer
    assert "THESISTRACE_AGENT_MODEL_REGISTRY" not in agent_initializer
    assert "THESISTRACE_MCP_" not in agent_initializer
    assert "THESISTRACE_AUTH_INTERNAL_ORIGIN: http://auth:8200" in api
    assert "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK" in api
    assert "THESISTRACE_MCP_DEPLOYMENT_TOOLS" in api
    assert "THESISTRACE_MCP_ALLOWED_HOSTS" in api
    assert "THESISTRACE_MCP_SIGNING_PRIVATE_JWK" not in api
    assert "THESISTRACE_MCP_AGENT_SCOPES" not in api
    assert all(
        "THESISTRACE_AUTH_INTERNAL_ORIGIN" not in worker
        and "THESISTRACE_MCP_" not in worker
        for worker in (research_worker, batch_worker, tracking_worker)
    )
    assert "condition: service_completed_successfully" in auth
    assert "depends_on:" not in web
    assert "THESISTRACE_API_ORIGIN" not in web


def test_production_overlay_publishes_only_caddy_and_persists_certificates() -> None:
    production = (DEPLOY / "compose.production.yaml").read_text()

    web = _service(production, "web")
    assert '      - "80:80"' in web
    assert '      - "443:443"' in web
    assert "      - caddy-data:/data" in web
    assert (
        "THESISTRACE_CADDY_HSTS_DIRECTIVE: "
        "'header >Strict-Transport-Security \"max-age=31536000\"'"
    ) in web
    assert production.count("    ports:\n") == 1
    assert production.count(":80") == 1
    assert production.count(":443") == 1
    assert "  caddy-data:\n" in production
    for service in ("postgres", "rustfs", "auth", "agent", "api"):
        assert f"  {service}:\n" not in production


def test_single_node_services_have_one_replica_and_restart_unless_stopped() -> None:
    compose = (DEPLOY / "compose.yaml").read_text()
    ordered_services = (
        ("postgres", "rustfs"),
        ("rustfs", "auth-initialize"),
        ("auth", "agent"),
        ("agent", "agent-initialize"),
        ("api", "research-worker"),
        ("research-worker", "batch-research-worker"),
        ("batch-research-worker", "tracking-worker"),
        ("tracking-worker", "web"),
        ("web", None),
    )
    for service, next_service in ordered_services:
        section = _service(compose, service, next_service)
        assert 'restart: unless-stopped' in section, service
        assert "deploy:\n      replicas: 1" in section, service

    for initializer, next_service in (
        ("auth-initialize", "auth"),
        ("initialize", "api"),
    ):
        section = _service(compose, initializer, next_service)
        assert 'restart: "no"' in section
        assert "unless-stopped" not in section


def test_development_and_test_origins_are_exact_before_compose_rendering() -> None:
    development = (DEPLOY / "compose.dev.yaml").read_text()
    development_env = (DEPLOY / "dev.env").read_text()
    test_overlay = (DEPLOY / "compose.test-run.yaml").read_text()
    runner = (ROOT / "scripts" / "test-runtime").read_text()

    assert "THESISTRACE_PUBLIC_ORIGIN=http://127.0.0.1:5173" in development_env
    assert "THESISTRACE_ENVIRONMENT=development" in development_env
    assert "THESISTRACE_AGENT_IMAGE=thesistrace-agent-dev" in development_env
    assert "THESISTRACE_MCP_SIGNING_PRIVATE_JWK=" in development_env
    assert "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK=" in development_env
    assert "THESISTRACE_MCP_INTERNAL_URL" not in development_env
    assert "127.0.0.1:${THESISTRACE_DEV_WEB_PORT}:5173" in development
    assert "127.0.0.1:${THESISTRACE_DEV_API_PORT}:8100" in development

    assert (
        "127.0.0.1:${THESISTRACE_TEST_CADDY_PORT}:"
        "${THESISTRACE_TEST_CADDY_PORT}" in test_overlay
    )
    assert "127.0.0.1::8100" not in test_overlay
    assert "127.0.0.1::5173" not in test_overlay
    assert "locked-loopback-port" in runner
    assert "THESISTRACE_TEST_CADDY_PORT=\"$caddy_port\"" in runner
    assert "THESISTRACE_PUBLIC_ORIGIN=\"$public_origin\"" in runner
    assert 'THESISTRACE_AGENT_IMAGE="$project_name-agent"' in runner
    assert 'THESISTRACE_MCP_SIGNING_PRIVATE_JWK="$mcp_signing_private_jwk"' in runner
    assert runner.index("caddy_port=") < runner.index("compose config --quiet")


def test_active_deployment_contains_no_nginx_contract() -> None:
    active = "\n".join(
        path.read_text(errors="ignore")
        for path in DEPLOY.rglob("*")
        if path.is_file()
    ).lower()
    assert "nginx" not in active


def test_release_image_gate_uses_the_same_caddyfile_with_an_internal_test_ca() -> None:
    package = (ROOT / "package.json").read_text()
    smoke = (ROOT / "scripts" / "test-caddy-production-image").read_text()

    assert '"test:caddy-image-smoke": "./scripts/test-caddy-production-image"' in package
    assert "pnpm test:caddy-image-smoke" in package
    assert "THESISTRACE_PUBLIC_ORIGIN=https://thesistrace.test" in smoke
    assert "THESISTRACE_CADDY_TLS_DIRECTIVE=tls internal" in smoke
    assert (
        "THESISTRACE_CADDY_HSTS_DIRECTIVE=header >Strict-Transport-Security "
        "\"max-age=31536000\""
    ) in smoke
    assert "308 Permanent Redirect" in smoke
    assert "internal/session/verify private-internal" in smoke
    assert "certificates_after" in smoke
    assert "certificates_before" in smoke
    assert "Caddyfile.header-echo.test" in smoke
    assert "203.0.113.250" in smoke
    assert "client_ip_one" in smoke
    assert "client_ip_two" in smoke
    assert "forged_request_id" in smoke
    assert "Content-Security-Policy" in smoke
    assert "Strict-Transport-Security" in smoke
    assert "includeSubDomains" in smoke
    assert "preload" in smoke
    assert "request-canary" in smoke
    assert '"logger":"http.log.error.log0"' in smoke
    for evidence_name in (
        "caddy.log",
        "container-inspect.json",
        "image-inspect.json",
        "network-inspect.json",
        "volume-inspect.json",
        "docker-version.txt",
        "final-status.txt",
    ):
        assert evidence_name in smoke


def test_image_smoke_exposes_only_caddy_through_a_noninternal_edge_network() -> None:
    overlay = (DEPLOY / "compose.image-smoke.yaml").read_text()

    assert "  default:\n    internal: true" in overlay
    assert "  edge:\n" in overlay
    web = _service(overlay, "web")
    assert "    networks:\n      - default\n      - edge\n" in web


def test_failed_caddy_image_smoke_captures_evidence_before_cleanup(
    tmp_path: Path,
) -> None:
    command_log = tmp_path / "docker-commands.log"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
with Path(os.environ["CADDY_SMOKE_COMMAND_LOG"]).open("a") as stream:
    stream.write(f"docker {' '.join(arguments)}\\n")

if arguments[0] == "build":
    raise SystemExit(0)
if arguments[:2] == ["network", "create"]:
    print("network-id")
    raise SystemExit(0)
if arguments[:2] == ["volume", "create"]:
    print("volume-name")
    raise SystemExit(0)
if arguments[0] == "run":
    print("container-id")
    raise SystemExit(0)
if arguments[0] == "exec":
    url = arguments[-1]
    if url.endswith("/data"):
        raise SystemExit(0)
    if url.endswith("/login"):
        print('<html><div id="root"></div></html>')
        raise SystemExit(0)
    if url == "http://thesistrace.test/":
        print("  HTTP/1.1 308 Permanent Redirect", file=sys.stderr)
        print("  Location: https://thesistrace.test/", file=sys.stderr)
        raise SystemExit(0)
    if url.endswith("/health/live") and "--quiet" in arguments:
        raise SystemExit(0)
    raise SystemExit(1)
if arguments[0] == "version":
    print("fake docker version")
    raise SystemExit(0)
if arguments[0] == "logs":
    print("fake caddy log")
    raise SystemExit(0)
if arguments[:2] == ["container", "inspect"]:
    print('[{"State":{"Status":"running"}}]')
    raise SystemExit(0)
if arguments[:2] == ["image", "inspect"]:
    print('[{"Id":"sha256:caddy-smoke"}]')
    raise SystemExit(0)
if arguments[:2] == ["network", "inspect"]:
    print('[{"Name":"caddy-network"}]')
    raise SystemExit(0)
if arguments[:2] == ["volume", "inspect"]:
    print('[{"Name":"caddy-data"}]')
    raise SystemExit(0)
if arguments[:2] in (["rm", "--force"], ["network", "rm"], ["volume", "rm"], ["image", "rm"]):
    raise SystemExit(0)
raise SystemExit(2)
"""
    )
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
        "CADDY_SMOKE_COMMAND_LOG": str(command_log),
    }

    completed = subprocess.run(
        [ROOT / "scripts" / "test-caddy-production-image"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 1
    match = re.search(r"Caddy Production image-smoke evidence: (.+)", completed.stderr)
    assert match is not None
    evidence = Path(match.group(1))
    assert (evidence / "caddy.log").read_text().strip() == "fake caddy log"
    assert "running" in (evidence / "container-inspect.json").read_text()
    assert "sha256:caddy-smoke" in (evidence / "image-inspect.json").read_text()
    assert (evidence / "docker-version.txt").read_text().strip() == (
        "fake docker version"
    )
    assert (evidence / "cleanup-status.txt").read_text() == "0\n"
    assert (evidence / "final-status.txt").read_text() == "1\n"
    commands = command_log.read_text()
    assert commands.index("docker logs") < commands.index("docker rm --force")
