from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def compose_model() -> dict[str, object]:
    return yaml.safe_load((ROOT / "deploy/hosted/compose.yaml").read_text())


def test_product_migrations_wait_for_the_identity_schema() -> None:
    dependencies = compose_model()["services"]["thesistrace-migrations"]["depends_on"]
    assert dependencies["insforge-migrations"] == {"condition": "service_completed_successfully"}


def test_only_edge_is_published() -> None:
    services = compose_model()["services"]
    published = {name: service["ports"] for name, service in services.items() if "ports" in service}
    assert set(published) == {"edge"}


def test_compose_and_launcher_have_no_operations_processes() -> None:
    compose = (ROOT / "deploy/hosted/compose.yaml").read_text().lower()
    launcher = (ROOT / "scripts/hosted-stack").read_text().lower()
    removed = (
        "health" + "-service",
        "backup" + "-tool",
        "restore" + "-tool",
        "restore" + "-gate",
        "otel" + "-collector",
        "prom" + "etheus",
        "gra" + "fana",
        "maintenance" + "-enter",
        "maintenance" + "-exit",
    )
    for token in removed:
        assert token not in compose
        assert token not in launcher
