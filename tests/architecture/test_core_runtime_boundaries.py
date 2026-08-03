import ast
from pathlib import Path

from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings

ROOT = Path(__file__).resolve().parents[2]
CORE_PACKAGES = ("_postgres", "data", "entrypoints", "publication")
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
                node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
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
        path.read_text() for path in (ROOT / "src" / "thesistrace" / "_postgres").rglob("*.py")
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

    data_migrations = (ROOT / "src" / "thesistrace" / "data" / "migrations.py").read_text()
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


def test_alpha_tree_has_one_legacy_parser_and_no_dynamic_execution() -> None:
    alpha_source = (ROOT / "src" / "thesistrace" / "alpha.py").read_text()
    normalized_source = (
        ROOT / "src" / "thesistrace" / "research_kernel" / "alpha_expression.py"
    ).read_text()
    assert alpha_source.count("ast.parse(") == 1
    assert "def validate_legacy_alpha(" in alpha_source
    for forbidden in ("eval(", "exec(", "importlib", "sql"):
        assert forbidden not in normalized_source.lower()


def test_data_owns_the_single_authorable_field_binding_catalog() -> None:
    data_fields = (ROOT / "src" / "thesistrace" / "data" / "fields.py").read_text()
    alpha_source = (ROOT / "src" / "thesistrace" / "alpha.py").read_text()
    fixture_source = (ROOT / "src" / "thesistrace" / "fixture.py").read_text()

    for field_id in (
        "price.open.adjusted",
        "price.high.adjusted",
        "price.low.adjusted",
        "price.close.adjusted",
        "market.volume.shares",
        "market.turnover.cny",
    ):
        assert data_fields.count(field_id) == 1
        assert field_id not in alpha_source
        assert field_id not in fixture_source


def test_publication_hides_physical_s3_keys_and_uses_the_standard_client() -> None:
    source = (ROOT / "src" / "thesistrace" / "publication" / "service.py").read_text()
    exported = (ROOT / "src" / "thesistrace" / "publication" / "__init__.py").read_text()

    assert "put_object(" in source
    assert "get_object(" in source
    assert "httpx" not in source
    assert "_object_key" in source
    assert "object_key" not in exported
    assert "s3" not in CoreRuntime.__dataclass_fields__
    assert "thesistrace.objects" not in source
    assert (ROOT / "src" / "thesistrace" / "publication" / "serialization.py").is_file()
    for forbidden in ("token", "proxy", "fastapi", "filesystem"):
        assert forbidden not in source.lower()


def test_publication_owns_its_sql_and_never_commits_a_caller_transaction() -> None:
    service = (ROOT / "src" / "thesistrace" / "publication" / "service.py").read_text()
    migrations = (ROOT / "src" / "thesistrace" / "publication" / "migrations.py").read_text()

    assert "CREATE TABLE publication.objects" in migrations
    assert "CREATE TABLE publication.manifests" in migrations
    assert "CREATE TABLE publication.manifest_objects" in migrations
    assert "def record(" in service
    assert ".commit(" not in service
    for product_schema in ("data.", "definitions.", "research_runs.", "daily_tracks."):
        assert product_schema not in service
        assert product_schema not in migrations
