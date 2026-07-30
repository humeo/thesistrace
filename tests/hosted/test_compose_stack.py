import json
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
    } <= volume_names

    assert set(services["deno"]["networks"]) == {"control"}
    deno_dockerfile = (ROOT / "deploy" / "hosted" / "Dockerfile.deno").read_text()
    assert "RUN deno cache server.ts" in deno_dockerfile


def test_hosted_processes_use_explicit_database_and_worker_roles() -> None:
    services = compose_model()["services"]
    assert services["api"]["environment"]["THESISTRACE_RUNTIME_MODE"] == "hosted"
    assert services["api"]["environment"]["THESISTRACE_DATABASE_ROLE"] == "api"
    assert services["data-worker"]["environment"]["THESISTRACE_DATABASE_ROLE"] == "data"
    assert services["data-worker"]["command"][1:3] == ["--role", "data"]
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
