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


def test_hosted_stack_declares_the_complete_pinned_topology() -> None:
    model = compose_model()
    services = model["services"]
    required = {
        "edge",
        "api",
        "postgres",
        "postgrest",
        "insforge",
        "insforge-migrations",
        "deno",
        "temporal",
        "temporal-schema",
        "temporal-namespace",
        "thesistrace-migrations",
        "volume-permissions",
        "release-gate",
        "execution-relay",
        "object-store",
        "tushare-egress",
        "data-worker",
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
        "otel-collector",
        "prometheus",
        "grafana",
        "health-service",
        "backup-tool",
        "restore-gate",
    }
    assert required <= services.keys()

    for name, service in services.items():
        image = service.get("image")
        if image is not None:
            assert ":" in image, name
            assert not image.endswith(":latest"), name


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
    assert "/api/storage/*" in caddyfile
    assert "/api/v1/objects/*" in caddyfile
    assert "/api/auth/admin/*" in caddyfile
    assert "handle @private_edge_paths" in caddyfile


def test_private_services_use_internal_networks_and_persistent_named_volumes() -> None:
    model = compose_model()
    services = model["services"]
    networks = model["networks"]
    assert networks["control"]["internal"] is True
    assert networks["execution"]["internal"] is True
    assert networks["observability"]["internal"] is True
    assert networks["storage"]["internal"] is True
    assert networks["tushare-egress"]["internal"] is True

    for name in {
        "postgres",
        "postgrest",
        "insforge",
        "temporal",
        "data-worker",
        "compute-worker-1",
        "prometheus",
    }:
        assert not services[name].get("ports"), name

    volume_names = set(model["volumes"])
    assert {
        "postgres-data",
        "insforge-storage",
        "temporal-data",
        "immutable-objects",
        "working-cache",
    } <= volume_names

    assert set(services["deno"]["networks"]) == {"control"}
    deno_dockerfile = (ROOT / "deploy" / "hosted" / "Dockerfile.deno").read_text()
    assert "RUN deno cache server.ts" in deno_dockerfile


def test_hosted_processes_use_explicit_database_and_worker_roles() -> None:
    services = compose_model()["services"]
    assert services["api"]["environment"]["THESISTRACE_RUNTIME_MODE"] == "hosted"
    assert services["api"]["environment"]["THESISTRACE_DATABASE_ROLE"] == "api"
    assert services["data-worker"]["environment"]["THESISTRACE_DATABASE_ROLE"] == "data"
    assert services["data-worker"]["command"] == ["thesistrace-data-worker"]
    assert services["execution-relay"]["environment"]["THESISTRACE_DATABASE_ROLE"] == "relay"
    assert services["execution-relay"]["command"][0] == "thesistrace-execution-relay"
    for name in {
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
    }:
        assert services[name]["environment"]["THESISTRACE_DATABASE_ROLE"] == "compute"
        assert services[name]["command"][0] == "thesistrace-temporal-worker"
    assert [
        services[f"compute-worker-{index}"]["environment"][
            "THESISTRACE_COMPUTE_SLOT_PREFERENCE"
        ]
        for index in range(1, 5)
    ] == ["p1", "p1", "p1", "p3"]
    assert [
        services[f"compute-worker-{index}"]["environment"][
            "THESISTRACE_COMPUTE_WORKFLOW_POLLER"
        ]
        for index in range(1, 5)
    ] == ["true", "false", "false", "false"]


def test_five_workers_have_isolated_single_slot_container_boundaries() -> None:
    services = compose_model()["services"]
    compute_names = sorted(
        name
        for name in services
        if name.startswith("compute-worker-")
    )
    assert compute_names == [
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
    ]
    worker_names = [*compute_names, "data-worker"]
    for name in worker_names:
        worker = services[name]
        assert worker["read_only"] is True
        assert worker["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in worker["security_opt"]
        assert worker["pids_limit"] == 256
        assert worker["user"] != "0:0"
        assert worker.get("privileged") is not True
        assert any(
            item.startswith("/tmp:size=")
            for item in worker["tmpfs"]
        )
        assert "/var/run/docker.sock" not in json.dumps(worker)
        assert worker["mem_limit"] == "1073741824"

    for name in compute_names:
        worker = services[name]
        assert worker["cpus"] == 0.75
        assert set(worker["networks"]) == {
            "control",
            "execution",
            "observability",
            "storage",
        }
        assert worker["volumes"] == [
            {
                "type": "volume",
                "source": "working-cache",
                "target": "/var/lib/thesistrace/working-cache",
                "volume": {},
            }
        ]
        assert worker["group_add"] == ["11000"]
        assert "TUSHARE_TOKEN" not in worker["environment"]

    data = services["data-worker"]
    assert data["cpus"] == 0.5
    assert set(data["networks"]) == {
        "control",
        "execution",
        "observability",
        "storage",
        "tushare-egress",
    }
    assert not data.get("volumes")
    assert data["environment"]["TUSHARE_TOKEN_FILE"] == "/run/secrets/tushare_token"
    assert data["environment"]["HTTPS_PROXY"] == (
        "http://tushare-egress:8080"
    )

    egress = services["tushare-egress"]
    assert egress["user"] == "10006:10006"
    assert egress["read_only"] is True
    assert egress["cap_drop"] == ["ALL"]
    assert set(egress["networks"]) == {
        "tushare-egress",
        "data-egress",
        "observability",
    }
    assert not egress.get("environment")
    assert {
        name
        for name, service in services.items()
        if "data-egress" in service.get("networks", {})
    } == {"tushare-egress"}

    compute_worker = (
        ROOT / "src" / "thesistrace" / "hosted" / "temporal_worker.py"
    ).read_text()
    data_worker = (
        ROOT / "src" / "thesistrace" / "hosted" / "data_worker.py"
    ).read_text()
    assert "max_concurrent_activities=1" in compute_worker
    assert "max_concurrent_activities=1" in data_worker


def test_private_object_store_is_the_only_steady_immutable_volume_owner() -> None:
    services = compose_model()["services"]
    immutable_owners = {
        name
        for name, service in services.items()
        if any(
            volume.get("source") == "immutable-objects"
            for volume in service.get("volumes", [])
        )
    }
    assert immutable_owners == {
        "object-store",
        "volume-permissions",
        "backup-tool",
        "restore-tool",
        "restore-gate",
    }
    assert {
        name
        for name in immutable_owners
        if not services[name].get("profiles")
    } == {"object-store", "volume-permissions"}
    storage = services["object-store"]
    assert storage["user"] == "10005:10005"
    assert storage["read_only"] is True
    assert storage["cap_drop"] == ["ALL"]
    assert set(storage["networks"]) == {
        "storage",
        "observability",
    }
    assert "THESISTRACE_DATABASE_URL" not in storage["environment"]
    assert services["api"]["depends_on"]["object-store"]["condition"] == (
        "service_healthy"
    )
    for name in {
        "api",
        "data-worker",
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
    }:
        assert services[name]["environment"][
            "THESISTRACE_OBJECT_STORE_URL"
        ] == "http://object-store:8010"


def test_steady_services_use_distinct_identities_and_secrets() -> None:
    services = compose_model()["services"]
    identities = {
        name: services[name]["user"]
        for name in (
            "api",
            "execution-relay",
            "data-worker",
            "compute-worker-1",
            "object-store",
            "tushare-egress",
        )
    }
    assert len(set(identities.values())) == len(identities)

    database_services = {
        "api": "thesistrace_api",
        "execution-relay": "thesistrace_relay",
        "data-worker": "thesistrace_data",
        "compute-worker-1": "thesistrace_compute",
    }
    assert {
        name: services[name]["environment"]["THESISTRACE_DATABASE_USER"]
        for name in database_services
    } == database_services
    database_secret_files = {
        services[name]["environment"]["THESISTRACE_DATABASE_PASSWORD_FILE"]
        for name in database_services
    }
    assert len(database_secret_files) == len(database_services)
    assert all(path.startswith("/run/secrets/") for path in database_secret_files)
    assert all(
        "THESISTRACE_DATABASE_URL" not in services[name]["environment"]
        for name in database_services
    )

    object_token_files = {
        services[name]["environment"]["THESISTRACE_OBJECT_STORE_TOKEN_FILE"]
        for name in (
            "api",
            "data-worker",
            "compute-worker-1",
        )
    }
    assert len(object_token_files) == 3
    assert "THESISTRACE_OBJECT_STORE_TOKEN" not in services[
        "execution-relay"
    ]["environment"]

    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    for secret in {
        "THESISTRACE_API_DATABASE_PASSWORD",
        "THESISTRACE_RELAY_DATABASE_PASSWORD",
        "THESISTRACE_DATA_DATABASE_PASSWORD",
        "THESISTRACE_COMPUTE_DATABASE_PASSWORD",
        "THESISTRACE_HEALTH_DATABASE_PASSWORD",
        "THESISTRACE_OBJECT_STORE_API_TOKEN",
        "THESISTRACE_OBJECT_STORE_COMPUTE_TOKEN",
        "THESISTRACE_OBJECT_STORE_DATA_TOKEN",
    }:
        assert f"append_secret_if_missing {secret}" in launcher
        assert f"move_secret_to_file {secret} " in launcher
    assert "seal-recovery" in launcher
    assert "THESISTRACE_HOST_STATE_DIR" in launcher


def test_backup_and_restore_are_bounded_operator_only_surfaces() -> None:
    services = compose_model()["services"]
    backup = services["backup-tool"]
    assert backup["profiles"] == ["operator"]
    assert backup["network_mode"] == "none"
    assert backup["user"] == "0:0"
    assert backup["read_only"] is True
    assert backup["cap_drop"] == ["ALL"]
    assert backup["cap_add"] == ["DAC_READ_SEARCH"]
    assert "/var/run/docker.sock" not in json.dumps(backup)
    mounted = {
        (volume["source"], volume["target"], volume.get("read_only", False))
        for volume in backup["volumes"]
    }
    assert {
        ("postgres-data", "/backup/source/postgres-data", True),
        ("temporal-data", "/backup/source/temporal-data", True),
        ("immutable-objects", "/backup/source/immutable-objects", True),
        ("insforge-storage", "/backup/source/insforge-storage", True),
    } <= mounted

    restore = services["restore-tool"]
    assert restore["cap_drop"] == ["ALL"]
    assert restore["cap_add"] == ["CHOWN", "DAC_OVERRIDE", "FOWNER"]

    restore_gate = services["restore-gate"]
    assert restore_gate["profiles"] == ["operator"]
    assert restore_gate["read_only"] is True
    assert restore_gate["cap_drop"] == ["ALL"]
    assert set(restore_gate["networks"]) == {"control"}
    assert any(
        volume["source"] == "immutable-objects"
        and volume["target"] == "/var/lib/thesistrace/objects"
        and volume["read_only"] is True
        for volume in restore_gate["volumes"]
    )

    recovery_probe = services["recovery-probe"]
    assert recovery_probe["profiles"] == ["operator"]
    assert recovery_probe["read_only"] is True
    assert recovery_probe["cap_drop"] == ["ALL"]
    assert set(recovery_probe["networks"]) == {"execution"}
    assert "volumes" not in recovery_probe
    assert "secrets" not in recovery_probe

    health = services["health-service"]
    assert health["environment"]["THESISTRACE_BACKUP_STATUS_FILE"] == (
        "/run/thesistrace-backup/backup-status.json"
    )
    assert any(
        volume["target"] == "/run/thesistrace-backup"
        and volume["read_only"] is True
        for volume in health["volumes"]
    )


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
    backup_cli = (
        ROOT / "src" / "thesistrace" / "hosted" / "backup_cli.py"
    ).read_text()
    assert "RECOVERY_OPERATION_BUSY" in backup_cli
    assert "--recovery-selection" in launcher
    assert "--expected-backup-id" in launcher
    assert "thesistrace-recovery-probe verify" in launcher
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
    assert restore_section.index("thesistrace-recovery-probe verify") < (
        restore_section.index("compose up --detach --wait --no-build edge")
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
    outbox = state_root / "backup-health" / "recovery-audit-outbox"
    events = list(outbox.glob("audit_recovery_busy_*.json"))
    assert len(events) == 1
    assert json.loads(events[0].read_text())["reason_code"] == (
        "RECOVERY_OPERATION_BUSY"
    )


def test_one_shot_migrations_gate_every_public_or_steady_application_service() -> None:
    model = compose_model()
    services = model["services"]
    assert services["insforge-migrations"]["restart"] == "no"
    assert services["temporal-schema"]["restart"] == "no"
    assert services["thesistrace-migrations"]["restart"] == "no"
    assert services["release-gate"]["restart"] == "no"
    assert services["volume-permissions"]["restart"] == "no"
    assert services["volume-permissions"]["user"] == "0:0"
    assert services["thesistrace-migrations"]["depends_on"]["volume-permissions"][
        "condition"
    ] == "service_completed_successfully"

    release_dependencies = services["release-gate"]["depends_on"]
    assert release_dependencies["insforge-migrations"]["condition"] == (
        "service_completed_successfully"
    )
    assert release_dependencies["temporal-namespace"]["condition"] == (
        "service_completed_successfully"
    )
    assert release_dependencies["thesistrace-migrations"]["condition"] == (
        "service_completed_successfully"
    )

    for name in {
        "api",
        "edge",
        "data-worker",
        "execution-relay",
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
        "health-service",
    }:
        assert services[name]["depends_on"]["release-gate"]["condition"] == (
            "service_completed_successfully"
        )


def test_health_views_are_private_bounded_and_separately_provisioned() -> None:
    model = compose_model()
    services = model["services"]
    health = services["health-service"]
    assert not health.get("ports")
    assert set(health["networks"]) == {
        "edge",
        "control",
        "execution",
        "observability",
        "storage",
        "tushare-egress",
    }
    assert health["environment"]["THESISTRACE_DATABASE_ROLE"] == "health"
    assert health["environment"]["THESISTRACE_DISK_WARNING_PERCENT"] == "70"
    assert health["command"] == ["thesistrace-health-service"]
    assert set(health["depends_on"]) == {"release-gate"}
    assert set(services["grafana"]["networks"]) == {
        "observability",
        "operator",
    }
    assert model["networks"]["operator"].get("internal") is not True
    assert {
        name
        for name, service in services.items()
        if "operator" in service.get("networks", {})
    } == {"grafana"}

    for service in services.values():
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-file": "5", "max-size": "20m"},
        }

    prometheus = (ROOT / "deploy" / "hosted" / "prometheus.yaml").read_text()
    assert "health-service:8020" in prometheus
    assert "otel-collector:8888" in prometheus

    provisioning = ROOT / "deploy" / "hosted" / "grafana" / "provisioning"
    dashboards = sorted((provisioning / "dashboards").glob("*.json"))
    assert [path.name for path in dashboards] == [
        "data-health.json",
        "quantitative-semantic-health.json",
        "system-health.json",
    ]
    for path in dashboards:
        dashboard = json.loads(path.read_text())
        assert dashboard["title"].endswith("Health")
        assert not dashboard.get("alert")
        assert all("alert" not in panel for panel in dashboard["panels"])
        expected_view = {
            "system-health.json": 'view=\\"system\\"',
            "data-health.json": 'view=\\"data\\"',
            "quantitative-semantic-health.json": 'view=\\"quantitative\\"',
        }[path.name]
        assert expected_view in path.read_text()

    system_dashboard = (provisioning / "dashboards" / "system-health.json").read_text()
    assert 'up{job=\\"service-probes\\"' in system_dashboard
    assert "compute-worker-[1-4]:9100" in system_dashboard
    assert "vector(0)" in system_dashboard
    for path in dashboards:
        dashboard = json.loads(path.read_text())
        primary = dashboard["panels"][0]
        assert primary["fieldConfig"]["defaults"]["min"] == 0
        assert primary["fieldConfig"]["defaults"]["max"] == 1
        assert primary["fieldConfig"]["defaults"]["thresholds"]["steps"] == [
            {"color": "red", "value": None},
            {"color": "green", "value": 1},
        ]


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
        "temporal:7233",
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
