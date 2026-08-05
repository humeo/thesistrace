import fcntl
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "hosted" / "compose.yaml"


def compose_model() -> dict[str, object]:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "-f",
            str(COMPOSE),
            "--profile",
            "operator",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_api_readiness_window_covers_its_constrained_cpu_budget() -> None:
    api = compose_model()["services"]["api"]

    assert api["healthcheck"]["timeout"] == "20s"
    assert "timeout=15" in " ".join(api["healthcheck"]["test"])


def test_product_migrations_wait_for_the_insforge_identity_schema() -> None:
    dependencies = compose_model()["services"]["thesistrace-migrations"]["depends_on"]

    assert dependencies["insforge-migrations"] == {
        "condition": "service_completed_successfully",
        "required": True,
    }


def test_only_edge_is_public_and_grafana_is_loopback_only() -> None:
    model = compose_model()
    services = model["services"]
    published = {
        name: service["ports"]
        for name, service in services.items()
        if service.get("ports")
    }
    assert set(published) == {"edge", "grafana"}
    assert {
        int(binding["published"]) for binding in published["edge"]
    } == {80, 443}
    assert published["grafana"] == [
        {
            "mode": "ingress",
            "target": 3000,
            "published": "3001",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        }
    ]

    edge = services["edge"]
    assert edge["build"]["dockerfile"] == "deploy/hosted/Dockerfile.edge"
    assert "vite" not in json.dumps(edge).lower()
    caddyfile = (ROOT / "deploy" / "hosted" / "Caddyfile").read_text()
    assert "root * /srv" in caddyfile
    assert "reverse_proxy api:8000" in caddyfile
    assert "reverse_proxy insforge:7130" in caddyfile
    assert "@private_edge_paths" in caddyfile
    private_paths = next(
        line.split()[2:]
        for line in caddyfile.splitlines()
        if line.strip().startswith("@private_edge_paths path ")
    )
    assert "/api/storage/*" in private_paths
    assert "/storage/*" in private_paths
    assert "/api/v1/objects/*" in private_paths
    assert "/api/auth/admin/*" in private_paths
    assert "handle @private_edge_paths" in caddyfile


def test_backup_schedule_and_launcher_enforce_the_recovery_gate() -> None:
    timer = (ROOT / "deploy/hosted/systemd/thesistrace-backup.timer").read_text()
    assert "OnCalendar=*-*-* 00,06,12,18:00:00" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec" not in timer

    launcher = (ROOT / "scripts/hosted-stack").read_text()
    assert "backup-target-init)" in launcher
    assert "backup)" in launcher
    assert "restore)" in launcher
    assert "compose stop --timeout 30 edge" in launcher
    assert "python -m thesistrace.hosted.backup_cli verify-restore" in launcher
    assert "python -m thesistrace.hosted.backup_cli verify-runtime" in launcher
    assert "restore-release-modes --release-state" in launcher
    assert "backup.target.initialize succeeded" in launcher
    assert "backup.create succeeded" in launcher
    assert "backup.create rejected" in launcher
    assert "backup.restore succeeded" in launcher
    assert "backup.restore rejected" in launcher
    assert "audit-stage" in launcher
    assert "audit-flush" in launcher
    assert "OPERATION_INTERRUPTED" in launcher
    assert "lock-run" in launcher


def test_operator_mounts_capacity_evidence_from_the_host_read_only() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    operator_section = launcher.split("    operator)", 1)[1].split(
        "    maintenance-enter)", 1
    )[0]

    assert "capacity-qualification:record)" in operator_section
    assert 'operator_evidence_path="$operator_argument"' in operator_section
    assert 'if [ ! -f "$operator_evidence_path" ]; then' in operator_section
    assert (
        '--volume "$operator_evidence_path:$operator_evidence_path:ro"'
        in operator_section
    )
    backup_cli = (
        ROOT / "src" / "thesistrace" / "hosted" / "backup_cli.py"
    ).read_text()
    assert "RECOVERY_OPERATION_BUSY" in backup_cli
    assert "--recovery-selection" in launcher
    assert "--expected-backup-id" in launcher
    assert "--health-url http://health-service:8020/health/recovery" in launcher
    restore_section = launcher.split("restore_backup()", 1)[1].split(
        "action=", 1
    )[0]
    assert restore_section.index('. "$env_file"') < restore_section.index(
        '"$root/scripts/hosted-smoke.py"'
    )
    assert restore_section.index("verify-runtime") < restore_section.index(
        "compose up --detach --wait --no-build edge"
    )
    assert '--volume "$root:/workspace:ro"' not in restore_section
    assert launcher.index("compose stop --timeout 30 edge") < launcher.index(
        "python -m thesistrace.hosted.backup_cli verify-restore"
    )


def test_busy_recovery_lock_rejects_before_prepare_mutates_host_state(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "hosted-state"
    lock_path = state_root / "backup-health" / "recovery-operation.lock"
    lock_path.parent.mkdir(parents=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        completed = subprocess.run(
            [str(ROOT / "scripts" / "hosted-stack"), "backup"],
            cwd=ROOT,
            env={
                **os.environ,
                "THESISTRACE_HOST_STATE_DIR": str(state_root),
            },
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        os.close(descriptor)

    assert completed.returncode == 75
    assert "RECOVERY_OPERATION_BUSY" in completed.stdout
    assert not (state_root / "hosted.env").exists()
    assert not (state_root / "secrets").exists()
    assert not (state_root / "recovery").exists()
    outbox = state_root / "backup-health" / "operator-audit-outbox"
    events = list(outbox.glob("audit_recovery_busy_*.json"))
    assert len(events) == 1
    assert json.loads(events[0].read_text())["reason_code"] == (
        "RECOVERY_OPERATION_BUSY"
    )


def test_health_origin_defaults_to_public_site_and_local_override_is_explicit() -> None:
    health = compose_model()["services"]["health-service"]
    assert health["environment"]["THESISTRACE_PUBLIC_ORIGIN"] == "https://localhost"
    assert health["environment"]["THESISTRACE_PUBLIC_ORIGIN_INSECURE"] == "false"
    assert health["extra_hosts"] == ["host.docker.internal=host-gateway"]

    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    assert "https://host.docker.internal:" in launcher
    assert "environment_value THESISTRACE_HTTPS_PORT" in launcher
    assert "environment_value THESISTRACE_HEALTH_PUBLIC_ORIGIN" in launcher
    assert 'THESISTRACE_HEALTH_PUBLIC_ORIGIN_HOST="${health_host:-localhost}"' in launcher


def test_health_freshness_uses_latest_scheduled_research_session() -> None:
    migration = (
        ROOT
        / "deploy"
        / "hosted"
        / "migrations"
        / "0020_expected_research_session_health.sql"
    ).read_text()
    assert "dataset_release_matches_expected_session" in migration
    assert "publication.trigger_kind = 'schedule'" in migration
    assert "publication.kind IN ('live_bootstrap', 'live_increment')" in migration
    assert "publication.status = 'succeeded'" in migration
    assert "expected_release.manifest_json" in migration


def test_otel_sampling_and_export_failure_are_bounded_and_visible() -> None:
    collector = (ROOT / "deploy" / "hosted" / "otel-collector.yaml").read_text()
    assert "tail_sampling:" in collector
    assert "status_codes: [ERROR]" in collector
    assert "sampling_percentage: 100" in collector
    assert "sampling_percentage: 10" in collector
    assert "sampling_percentage: 1" in collector
    assert "otlp/external:" in collector
    assert "sending_queue:" in collector
    assert "queue_size: 2048" in collector
    assert "host: 0.0.0.0" in collector
    assert "port: 8888" in collector

    system_dashboard = (
        ROOT
        / "deploy"
        / "hosted"
        / "grafana"
        / "provisioning"
        / "dashboards"
        / "system-health.json"
    ).read_text()
    assert "otelcol_exporter_send_failed_spans" in system_dashboard


def test_public_origin_smoke_uses_no_private_service_address() -> None:
    smoke = (ROOT / "scripts" / "hosted-smoke.py").read_text()
    assert "THESISTRACE_HOSTED_ORIGIN" in smoke
    assert 'health.get("status") == "available"' in smoke
    for private_address in (
        "api:8000",
        "postgres:5432",
        "insforge:7130",
        "prometheus:9090",
        "grafana:3000",
    ):
        assert private_address not in smoke


def test_edge_accepts_only_verified_cloudflare_proxies_with_strict_tls() -> None:
    expected_ranges = set(
        (
            ROOT / "deploy" / "hosted" / "cloudflare-proxy-ranges.txt"
        ).read_text().splitlines()
    )
    edge = compose_model()["services"]["edge"]
    assert set(
        edge["environment"]["THESISTRACE_EDGE_TRUSTED_PROXIES"].split()
    ) == expected_ranges
    assert edge["environment"]["THESISTRACE_ORIGIN_TLS"] == (
        "/run/secrets/origin-tls/cert.pem "
        "/run/secrets/origin-tls/key.pem"
    )
    assert edge["read_only"] is True
    assert edge["cap_drop"] == ["ALL"]
    assert {port["target"] for port in edge["ports"]} == {8080, 8443}
    assert any(
        volume["target"] == "/run/secrets/origin-tls"
        and volume["read_only"] is True
        for volume in edge["volumes"]
    )

    caddyfile = (ROOT / "deploy" / "hosted" / "Caddyfile").read_text()
    assert "http_port 8080" in caddyfile
    assert "https_port 8443" in caddyfile
    assert "trusted_proxies static {$THESISTRACE_EDGE_TRUSTED_PROXIES}" in caddyfile
    assert "trusted_proxies_strict" in caddyfile
    assert "client_ip_headers CF-Connecting-IP" in caddyfile
    assert "@untrusted_origin not remote_ip {$THESISTRACE_EDGE_TRUSTED_PROXIES}" in caddyfile
    assert "handle @untrusted_origin" in caddyfile
    assert "respond 403" in caddyfile
    assert "tls {$THESISTRACE_ORIGIN_TLS}" in caddyfile

    edge_dockerfile = (
        ROOT / "deploy" / "hosted" / "Dockerfile.edge"
    ).read_text()
    assert "setcap -r /usr/bin/caddy" in edge_dockerfile


def test_api_and_cloudflare_limits_are_declared_at_the_identity_owning_layer() -> None:
    model = compose_model()
    api_environment = model["services"]["api"]["environment"]
    assert api_environment["THESISTRACE_API_RATE_LIMIT_WINDOW_SECONDS"] == "60"
    assert api_environment["THESISTRACE_API_USER_REQUEST_LIMIT"] == "120"
    assert api_environment["THESISTRACE_API_WORKSPACE_REQUEST_LIMIT"] == "240"
    assert api_environment["THESISTRACE_API_MUTATION_REQUEST_LIMIT"] == "30"

    policy = json.loads(
        (
            ROOT
            / "deploy"
            / "hosted"
            / "cloudflare-waf-rate-limits.json"
        ).read_text()
    )
    assert policy["characteristic"] == "ip"
    protected_paths = {
        path
        for rule in policy["rules"]
        for path in rule["paths"]
    }
    assert protected_paths == {
        "/api/auth/users",
        "/api/auth/sessions",
        "/api/auth/email/send-verification",
        "/api/auth/email/verify",
        "/api/auth/email/verify-link",
        "/api/auth/email/send-reset-password",
        "/api/auth/email/exchange-reset-password-token",
        "/api/auth/email/reset-password",
        "/api/auth/email/reset-password-link",
    }
    assert all(rule["period_seconds"] == 60 for rule in policy["rules"])
    assert all(rule["requests"] > 0 for rule in policy["rules"])


def test_origin_firewall_policy_allows_cloudflare_web_ingress_only() -> None:
    policy = (
        ROOT / "deploy" / "hosted" / "cloudflare-origin-firewall.nft"
    ).read_text()
    assert "set cloudflare_ipv4" in policy
    assert "set cloudflare_ipv6" in policy
    assert "tcp dport { 80, 443 } ip saddr @cloudflare_ipv4 accept" in policy
    assert "tcp dport { 80, 443 } ip6 saddr @cloudflare_ipv6 accept" in policy
    assert "tcp dport { 80, 443 } drop" in policy
    assert "type filter hook forward" in policy
    assert "ct status dnat ct original proto-dst { 80, 443 }" in policy
