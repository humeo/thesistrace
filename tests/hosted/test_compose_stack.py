import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

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
    }
    assert required <= services.keys()

    for name, service in services.items():
        image = service.get("image")
        if image is not None:
            assert ":" in image, name
            assert not image.endswith(":latest"), name


def test_only_edge_binds_host_ports_and_it_serves_the_static_build() -> None:
    model = compose_model()
    services = model["services"]
    published = {
        name: service["ports"]
        for name, service in services.items()
        if service.get("ports")
    }
    assert set(published) == {"edge"}
    assert {
        int(binding["published"]) for binding in published["edge"]
    } == {80, 443}

    edge = services["edge"]
    assert edge["build"]["dockerfile"] == "deploy/hosted/Dockerfile.edge"
    assert "vite" not in json.dumps(edge).lower()
    caddyfile = (ROOT / "deploy" / "hosted" / "Caddyfile").read_text()
    assert "root * /srv" in caddyfile
    assert "reverse_proxy api:8000" in caddyfile
    assert "reverse_proxy insforge:7130" in caddyfile
    assert "/api/storage" not in caddyfile


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
        "grafana",
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
    assert "TUSHARE_TOKEN" in data["environment"]
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


def test_private_object_store_is_the_only_immutable_volume_owner() -> None:
    services = compose_model()["services"]
    immutable_owners = {
        name
        for name, service in services.items()
        if any(
            volume.get("source") == "immutable-objects"
            for volume in service.get("volumes", [])
        )
    }
    assert immutable_owners == {"object-store", "volume-permissions"}
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
    parsed_urls = {
        name: urlparse(
            services[name]["environment"]["THESISTRACE_DATABASE_URL"]
        )
        for name in database_services
    }
    assert {
        name: parsed.username
        for name, parsed in parsed_urls.items()
    } == database_services
    assert len(
        {
            parsed.password
            for parsed in parsed_urls.values()
        }
    ) == len(parsed_urls)

    object_tokens = {
        services[name]["environment"]["THESISTRACE_OBJECT_STORE_TOKEN"]
        for name in (
            "api",
            "data-worker",
            "compute-worker-1",
        )
    }
    assert len(object_tokens) == 3
    assert "THESISTRACE_OBJECT_STORE_TOKEN" not in services[
        "execution-relay"
    ]["environment"]

    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    for secret in {
        "THESISTRACE_API_DATABASE_PASSWORD",
        "THESISTRACE_RELAY_DATABASE_PASSWORD",
        "THESISTRACE_DATA_DATABASE_PASSWORD",
        "THESISTRACE_COMPUTE_DATABASE_PASSWORD",
        "THESISTRACE_OBJECT_STORE_API_TOKEN",
        "THESISTRACE_OBJECT_STORE_COMPUTE_TOKEN",
        "THESISTRACE_OBJECT_STORE_DATA_TOKEN",
    }:
        assert f"append_secret_if_missing {secret}" in launcher


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
    }:
        assert services[name]["depends_on"]["release-gate"]["condition"] == (
            "service_completed_successfully"
        )


def test_public_origin_smoke_uses_no_private_service_address() -> None:
    smoke = (ROOT / "scripts" / "hosted-smoke.py").read_text()
    assert "THESISTRACE_HOSTED_ORIGIN" in smoke
    for private_address in (
        "api:8000",
        "postgres:5432",
        "insforge:7130",
        "temporal:7233",
        "prometheus:9090",
        "grafana:3000",
    ):
        assert private_address not in smoke
