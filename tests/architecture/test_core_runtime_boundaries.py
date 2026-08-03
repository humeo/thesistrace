import ast
from pathlib import Path

from thesistrace.entrypoints.runtime import CoreSettings

ROOT = Path(__file__).resolve().parents[2]
CORE_PACKAGES = ("_postgres", "data", "entrypoints")
FORBIDDEN_IMPORTS = (
    "thesistrace.hosted",
    "thesistrace.auth",
    "thesistrace.runtime",
    "temporalio",
)


def test_new_core_packages_do_not_import_old_or_hosted_runtime() -> None:
    for package in CORE_PACKAGES:
        for path in (ROOT / "src" / "thesistrace" / package).rglob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            ]
            imports.extend(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            assert not any(
                imported.startswith(forbidden)
                for imported in imports
                for forbidden in FORBIDDEN_IMPORTS
            ), f"{path} imports a forbidden runtime dependency"


def test_runtime_configuration_has_no_deployment_mode() -> None:
    assert "mode" not in CoreSettings.__dataclass_fields__


def test_postgres_support_contains_mechanics_but_no_product_sql() -> None:
    postgres_source = "\n".join(
        path.read_text()
        for path in (ROOT / "src" / "thesistrace" / "_postgres").rglob("*.py")
    )
    assert "ConnectionPool" in postgres_source
    assert "MigrationPlan" in postgres_source
    for product_schema in (
        "data.",
        "definitions.",
        "research_runs.",
        "daily_tracks.",
        "publication.",
    ):
        assert product_schema not in postgres_source

    data_migrations = (
        ROOT / "src" / "thesistrace" / "data" / "migrations.py"
    ).read_text()
    assert "CREATE TABLE data.state" in data_migrations
    assert "CREATE TABLE data.releases" in data_migrations


def test_isolated_runtime_pins_only_postgres_and_rustfs() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.test.yaml").read_text()
    assert "postgres:16.10-alpine" in compose
    assert "rustfs/rustfs:1.0.0-beta.12" in compose
    assert ":latest" not in compose
    for forbidden in ("sqlite", "temporal", "object-store", "auth"):
        assert forbidden not in compose.lower()


def test_web_shell_declares_only_the_four_product_resources() -> None:
    source = (ROOT / "web" / "src" / "shell" / "AppShell.tsx").read_text()
    assert source.count("path:") == 4
    assert 'path: "/data"' in source
    assert 'path: "/definitions"' in source
    assert 'path: "/research-runs"' in source
    assert 'path: "/daily-tracks"' in source
    for forbidden in ("hosted", "login", "workspace", "manifest", "download"):
        assert forbidden not in source.lower()
