import ast
import json
import subprocess
import sys
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import boto3
import pytest
from botocore.exceptions import ClientError

from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import (
    CORE_ENVIRONMENT_NAMES,
    PUBLICATION_REQUEST_TIMEOUT_SECONDS,
    CoreRuntime,
    CoreSettings,
    publication_request_config,
)

ROOT = Path(__file__).resolve().parents[2]
CORE_PACKAGES = (
    "_postgres",
    "benchmark",
    "data",
    "daily_track",
    "entrypoints",
    "operational_events",
    "publication",
    "research_authoring",
    "research_batch",
    "research_agent",
    "research_folder",
    "research_run",
    "researcher",
)
FORBIDDEN_IMPORTS = (
    "thesistrace." + "hosted",
    "thesistrace.auth",
    "thesistrace.runtime",
    "temporalio",
)
PRODUCT_SCHEMAS = {
    "data": "data",
    "research_run": "research_runs",
    "daily_track": "daily_tracks",
    "publication": "publication",
    "research_folder": "research_folders",
    "research_batch": "research_batches",
    "researcher": "researchers",
}
ALLOWED_SCHEMA_REFERENCES = {
    ("daily_track", "research_runs"),
    ("daily_track", "researchers"),
    ("research_batch", "research_folders"),
    ("research_batch", "research_runs"),
    ("research_batch", "researchers"),
    ("research_folder", "researchers"),
    ("research_run", "research_folders"),
    ("research_run", "researchers"),
    ("researcher", "research_folders"),
}


def test_research_agent_mcp_runbook_forwards_every_required_core_variable() -> None:
    runbook = (ROOT / "docs" / "runbook" / "research-agent-mcp.md").read_text()
    sample = runbook.split("```toml", maxsplit=1)[1].split("```", maxsplit=1)[0]
    server = tomllib.loads(sample)["mcp_servers"]["thesistrace"]

    assert set(CORE_ENVIRONMENT_NAMES) <= set(server["env_vars"])


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


def test_internal_import_graph_is_layered_and_acyclic() -> None:
    allowed = {
        "_postgres": set(),
        "benchmark": set(),
        "alpha_language": {"data", "research_kernel"},
        "publication": {"_postgres"},
        "research_series": set(),
        "research_kernel": {"research_series"},
        "data": {
            "_postgres",
            "benchmark",
            "operational_events",
            "product_state",
            "publication",
            "research_series",
        },
        "product_state": {"_postgres"},
        "research_folder": {"_postgres"},
        "researcher": {"_postgres", "research_folder"},
        "daily_track": {
            "_postgres",
            "benchmark",
            "data",
            "operational_events",
            "publication",
            "research_kernel",
            "research_series",
        },
        "research_run": {
            "_postgres",
            "alpha_language",
            "benchmark",
            "daily_track",
            "data",
            "operational_events",
            "publication",
            "research_folder",
            "research_kernel",
            "research_series",
        },
        "research_batch": {
            "_postgres",
            "alpha_language",
            "data",
            "publication",
            "research_folder",
                "research_kernel",
                "research_run",
                "research_series",
            },
        "research_authoring": {
            "alpha_language",
            "research_batch",
            "research_run",
        },
        "research_agent": {
            "alpha_language",
            "data",
            "daily_track",
            "operational_events",
            "research_authoring",
            "research_batch",
            "research_folder",
            "research_run",
        },
        "fixture": {"data"},
        "adapters": {"benchmark", "data", "fixture"},
        "entrypoints": {
            "_postgres",
            "alpha_language",
            "adapters",
            "benchmark",
            "daily_track",
            "data",
            "operational_events",
            "publication",
            "research_authoring",
            "research_batch",
            "research_agent",
            "research_folder",
            "research_kernel",
            "research_run",
            "researcher",
        },
        "operational_events": set(),
    }

    graph: dict[str, set[str]] = {}
    for package, allowed_dependencies in allowed.items():
        dependencies: set[str] = set()
        source = ROOT / "src" / "thesistrace" / package
        if not source.exists() and source.with_suffix(".py").is_file():
            source = source.with_suffix(".py")
        paths = [source] if source.is_file() else list(source.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text())
            dependencies.update(_internal_dependencies(path, tree) - {package})
        graph[package] = dependencies
        assert dependencies <= allowed_dependencies, (
            f"{package} imports outward dependencies: "
            f"{sorted(dependencies - allowed_dependencies)}"
        )
    assert set(graph) == set(allowed)
    assert all(
        dependency in graph
        for dependencies in graph.values()
        for dependency in dependencies
    )
    _assert_acyclic(graph)


def test_product_modules_own_their_schema_sql_and_lifecycle_tables() -> None:
    lifecycle_tables = {
        "data": (
            "data.current_dataset_state",
            "data.bootstrap_operations",
            "data.refresh_operations",
            "data.refresh_worker_leases",
            "data.refresh_cursor_secrets",
            "data.generation_candidates",
            "data.generation_pins",
        ),
        "research_run": (
            "research_runs.run_ownership",
            "research_runs.runs",
            "research_runs.admission_requests",
            "research_runs.attempts",
            "research_runs.cancel_receipts",
            "research_runs.cursor_secrets",
            "research_runs.start_tracking_receipts",
        ),
        "research_batch": (
            "research_batches.batches",
            "research_batches.items",
            "research_batches.progress",
            "research_batches.admission_receipts",
            "research_batches.cancel_receipts",
            "research_batches.cursor_secrets",
        ),
        "daily_track": (
            "daily_tracks.cursor_secrets",
            "daily_tracks.tracks",
            "daily_tracks.session_progressions",
            "daily_tracks.session_progression_attempts",
            "daily_tracks.session_checkpoints",
            "daily_tracks.retry_receipts",
            "daily_tracks.stop_receipts",
        ),
        "publication": (
            "publication.objects",
            "publication.manifests",
            "publication.manifest_objects",
            "publication.object_deletions",
        ),
        "research_folder": ("research_folders.folders",),
        "researcher": ("researchers.researchers",),
    }

    for module, owned_schema in PRODUCT_SCHEMAS.items():
        active_strings = "\n".join(
            _string_literals(path)
            for path in (ROOT / "src" / "thesistrace" / module).rglob("*.py")
            if path.name != "schema.sql"
        )
        for foreign_schema in set(PRODUCT_SCHEMAS.values()) - {owned_schema}:
            if (module, foreign_schema) in ALLOWED_SCHEMA_REFERENCES:
                continue
            assert f"{foreign_schema}." not in active_strings, (
                f"{module} source contains cross-schema SQL for {foreign_schema}"
            )

        statements = (ROOT / "src" / "thesistrace" / module / "schema.sql").read_text()
        for table in lifecycle_tables[module]:
            assert table in statements
        for foreign_schema in set(PRODUCT_SCHEMAS.values()) - {owned_schema}:
            if (module, foreign_schema) in ALLOWED_SCHEMA_REFERENCES:
                continue
            assert f"{foreign_schema}." not in statements


def test_runtime_configuration_has_no_deployment_mode() -> None:
    assert "mode" not in CoreSettings.__dataclass_fields__


def test_runtime_requires_independent_batch_attempt_control_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_mount = tmp_path / "canonical-data"
    attempt_control_directory = tmp_path / "batch-control" / ".batch-attempts"
    environment = {
        "THESISTRACE_DATABASE_URL": "postgresql://unused",
        "THESISTRACE_S3_ENDPOINT_URL": "http://unused",
        "THESISTRACE_S3_ACCESS_KEY_ID": "unused",
        "THESISTRACE_S3_SECRET_ACCESS_KEY": "unused",
        "THESISTRACE_S3_BUCKET": "unused",
        "THESISTRACE_DATA_MOUNT": str(data_mount),
        "THESISTRACE_BENCHMARK_MOUNT": str(tmp_path / "benchmark-data"),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            attempt_control_directory
        ),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    settings = CoreSettings.from_environment()

    assert settings.data_mount == data_mount
    assert settings.benchmark_mount == tmp_path / "benchmark-data"
    assert settings.batch_attempt_control_directory == attempt_control_directory
    assert not settings.batch_attempt_control_directory.is_relative_to(
        settings.data_mount
    )

    independent_mount = tmp_path / "independent-store" / "benchmark"
    monkeypatch.setenv("THESISTRACE_BENCHMARK_MOUNT", str(independent_mount))
    assert CoreSettings.from_environment().benchmark_mount == independent_mount

    monkeypatch.setenv("THESISTRACE_BENCHMARK_MOUNT", str(data_mount / "benchmark"))
    with pytest.raises(
        RuntimeError,
        match="must be independent of Canonical Data",
    ):
        CoreSettings.from_environment()
    monkeypatch.setenv(
        "THESISTRACE_BENCHMARK_MOUNT",
        str(tmp_path / "benchmark-data"),
    )

    monkeypatch.delenv("THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY")
    with pytest.raises(
        RuntimeError,
        match="THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
    ):
        CoreSettings.from_environment()

    monkeypatch.setenv(
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
        str(data_mount / ".batch-attempts"),
    )
    with pytest.raises(
        RuntimeError,
        match="must be outside THESISTRACE_DATA_MOUNT",
    ):
        CoreSettings.from_environment()


def test_default_backend_commands_resolve_only_to_canonical_entrypoints() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scripts = project["project"]["scripts"]

    assert scripts == {
        "thesistrace-core-api": "thesistrace.entrypoints.http:main",
        "thesistrace-core-access-inspect": "thesistrace.entrypoints.access_operator:main",
        "thesistrace-core-diagnose": "thesistrace.entrypoints.diagnose:main",
        "thesistrace-core-worker": "thesistrace.entrypoints.worker:main",
        "thesistrace-initialize": "thesistrace.entrypoints.initialize:main",
        "thesistrace-data-operator": "thesistrace.entrypoints.data_operator:main",
        "thesistrace-research-agent-mcp": (
            "thesistrace.entrypoints.research_agent_mcp:main"
        ),
    }


def test_core_diagnostic_entrypoint_is_postgresql_only() -> None:
    source = (ROOT / "src/thesistrace/entrypoints/diagnose.py").read_text()

    assert "PostgresDatabase" in source
    assert "ResearchRunDiagnostics" in source
    assert "DailyTrackDiagnostics" in source
    assert "open_core_runtime" not in source
    assert "Publication" not in source
    assert "DatasetLifecycle" not in source
    assert "MountedGenerationStore" not in source
    assert "boto" not in source


def test_long_running_runtime_verifies_but_does_not_initialize_schema() -> None:
    runtime_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "runtime.py").read_text()
    initializer_source = (
        ROOT / "src" / "thesistrace" / "entrypoints" / "initialize.py"
    ).read_text()
    runtime_body = runtime_source.split("def open_core_runtime", maxsplit=1)[1]

    assert "verify_core_schema(database)" in runtime_body
    assert "initialize_core(" not in runtime_body
    assert "initialize_core(database_url)" in initializer_source


def test_current_runtime_initializes_before_starting_long_running_processes() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.yaml").read_text()
    initialize_service = compose.split("  initialize:\n", maxsplit=1)[1].split(
        "  api:\n", maxsplit=1
    )[0]
    api_service = compose.split("  api:\n", maxsplit=1)[1].split(
        "  research-worker:\n", maxsplit=1
    )[0]
    research_worker = compose.split("  research-worker:\n", maxsplit=1)[1].split(
        "  batch-research-worker:\n", maxsplit=1
    )[0]
    batch_research_worker = compose.split(
        "  batch-research-worker:\n", maxsplit=1
    )[1].split("  tracking-worker:\n", maxsplit=1)[0]
    tracking_worker = compose.split("  tracking-worker:\n", maxsplit=1)[1].split(
        "  web:\n", maxsplit=1
    )[0]

    assert 'command: ["thesistrace-initialize"]' in initialize_service
    assert "condition: service_completed_successfully" in api_service
    assert "condition: service_completed_successfully" in research_worker
    assert "condition: service_completed_successfully" in batch_research_worker
    assert "condition: service_completed_successfully" in tracking_worker

    script = """
import json
import sys
from thesistrace.entrypoints import http, worker
del http, worker
forbidden = {
    name for name in sys.modules
    if name in {
        "sqlite3",
        "temporalio",
        "thesistrace.api",
        "thesistrace.auth",
        "thesistrace.runtime",
        "thesistrace.worker",
    }
    or name.startswith("thesistrace." + "hosted")
}
print(json.dumps(sorted(forbidden)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []


def test_postgres_support_contains_mechanics_but_no_product_sql() -> None:
    postgres_source = "\n".join(
        path.read_text() for path in (ROOT / "src" / "thesistrace" / "_postgres").rglob("*.py")
    )
    assert "ConnectionPool" in postgres_source
    assert "SchemaDefinition" in postgres_source
    for product_schema in (
        "data.",
        "definitions.",
        "research_runs.",
        "daily_tracks.",
        "publication.",
        "research_folders.",
        "researchers.",
    ):
        assert product_schema not in postgres_source

    data_schema = (ROOT / "src" / "thesistrace" / "data" / "schema.sql").read_text()
    assert "CREATE TABLE data.current_dataset_state" in data_schema
    assert "CREATE TABLE data.refresh_operations" in data_schema
    assert "CREATE TABLE data.refresh_worker_leases" in data_schema
    assert "CREATE TABLE data.refresh_cursor_secrets" in data_schema
    assert "last_heartbeat_at timestamp with time zone" in data_schema
    assert "phase text" in data_schema
    assert "'cancelled'::text" in data_schema
    assert "data.releases" not in data_schema


def test_canonical_compose_pins_external_infrastructure_images() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.yaml").read_text()
    assert "postgres:16.10-alpine" in compose
    assert "rustfs/rustfs:1.0.0-beta.12" in compose
    assert ":latest" not in compose
    for forbidden in ("sqlite", "temporal", "object-store"):
        assert forbidden not in compose.lower()
    assert "  auth-initialize:\n" in compose
    assert "  auth:\n" in compose


def test_web_shell_declares_only_the_four_product_resources() -> None:
    source = (ROOT / "web" / "src" / "shell" / "AppShell.tsx").read_text()
    main = (ROOT / "web" / "src" / "main.tsx").read_text()
    package = json.loads((ROOT / "web" / "package.json").read_text())
    browser = (ROOT / "web" / "playwright.config.ts").read_text()
    vite = (ROOT / "web" / "vite.config.ts").read_text()
    core_app = (ROOT / "web" / "src" / "shell" / "CoreApp.tsx").read_text()
    resource_routes = source.partition("] as const;")[0]
    for route in (
        'path: "/data"',
        'path: "/research"',
        'path: "/research-runs"',
        'path: "/daily-tracks"',
    ):
        assert resource_routes.count(route) == 1
    for forbidden in ("hosted", "login", "workspace", "manifest", "download"):
        assert forbidden not in resource_routes.lower()
    assert 'import { CoreApp } from "./shell/CoreApp"' in main
    assert "history.replaceState" in main
    for inactive in ('from "./App"', "HostedAuthBoundary", "isCoreRoute"):
        assert inactive not in main
    assert package["scripts"]["test:e2e"] == "playwright test"
    assert set(package["scripts"]) == {
        "build",
        "dev",
        "test:e2e",
        "test:shell",
        "typecheck",
    }
    assert "THESISTRACE_TEST_WEB_ORIGIN" in browser
    assert "THESISTRACE_TEST_EVIDENCE_DIR" in browser
    assert "retain-on-failure" in browser
    assert "webServer" not in browser
    assert "thesistrace-api" not in browser
    assert "thesistrace-worker" not in browser
    assert "vite --host" not in browser
    assert 'new URL("./index.html"' in vite
    assert 'new URL("./core.html"' not in vite
    assert 'pathname === "/core.html"' in vite
    assert "response.statusCode = 404" in vite
    assert "isCoreRoute" not in core_app
    assert "ResourceRoute" not in core_app
    for removed_path in (
        "core.html",
        "e2e",
        "e2e-hosted",
        "playwright.core-shell.config.ts",
        "playwright.hosted.config.ts",
        "src/App.tsx",
        "src/hostedAuth.tsx",
        "src/shell/main.tsx",
    ):
        assert not (ROOT / "web" / removed_path).exists()


def test_http_route_and_action_inventory_is_exactly_the_core_resources() -> None:
    assert _http_routes() == {
        ("get", "/api/alpha/catalog"),
        ("post", "/api/alpha/diagnostics"),
        ("get", "/api/data"),
        ("get", "/api/operator/data/status"),
        ("post", "/api/operator/data/refreshes/cancel"),
        ("get", "/api/operator/data/refreshes/financial"),
        ("post", "/api/operator/data/refreshes/financial"),
        ("get", "/api/operator/data/refreshes/industry"),
        ("post", "/api/operator/data/refreshes/industry"),
        ("get", "/api/operator/data/refreshes/market"),
        ("post", "/api/operator/data/refreshes/market"),
        ("post", "/api/operator/data/refreshes/retry"),
        ("post", "/api/researcher/bootstrap"),
        ("get", "/api/research-folders"),
        ("post", "/api/research-folders"),
        ("patch", "/api/research-folders/{folder_id}"),
        ("delete", "/api/research-folders/{folder_id}"),
        ("get", "/api/research-batches"),
        ("post", "/api/research-batches"),
        ("get", "/api/research-batches/{batch_id}"),
        ("post", "/api/research-batches/{batch_id}/cancel"),
        ("get", "/api/research-runs"),
        ("post", "/api/research-runs"),
        ("patch", "/api/research-runs/{run_id}"),
        ("delete", "/api/research-runs/{run_id}"),
        ("get", "/api/research-runs/{run_id}"),
        ("post", "/api/research-runs/{run_id}/cancel"),
        ("post", "/api/research-runs/{run_id}/daily-tracks"),
        ("get", "/api/daily-tracks"),
        ("get", "/api/daily-tracks/{track_id}"),
        ("delete", "/api/daily-tracks/{track_id}"),
        ("post", "/api/daily-tracks/{track_id}/retry"),
        ("post", "/api/daily-tracks/{track_id}/stop"),
    }


def test_default_gate_excludes_deferred_and_credential_dependent_work() -> None:
    core_gate = _package_script("check")
    live_gate = _package_script("check:live-tushare")

    assert core_gate == "pnpm test && pnpm test:integration && pnpm test:e2e"
    for deferred in (
        "hosted",
        "login",
        "deploy",
        "sqlite",
        "check-live-tushare",
        "check_live_tushare",
    ):
        assert deferred not in core_gate.lower()
    assert live_gate == "uv run python scripts/check_live_tushare.py"


def test_fast_host_gate_uses_bounded_parallelism_without_expensive_work() -> None:
    fast_gate = _package_script("test")

    for command in (
        "uv run ruff check src tests",
        "uv run pytest -q -n 4 tests/kernel tests/architecture tests/adapters tests/data",
        "pnpm --dir web typecheck",
        "pnpm --dir web test:shell",
    ):
        assert command in fast_gate
    for excluded in (
        "docker",
        "compose",
        "core-test-runtime",
        "test-runtime",
        "tests/integration",
        "tests/acceptance",
        "test:e2e",
        "check-live-tushare",
        "check_live_tushare",
        "hosted",
        "production",
    ):
        assert excluded not in fast_gate.lower()
    assert "-n auto" not in fast_gate


def test_hosted_identity_and_deployment_runtime_are_archived_only() -> None:
    removed_paths = (
        "deploy/hosted",
        "src/thesistrace/hosted",
        "tests/hosted",
        "scripts/hosted-stack",
        "scripts/hosted-auth-smoke.py",
        "scripts/hosted-release-smoke.py",
        "scripts/hosted-" + "smoke.py",
        "scripts/hosted/configure_smtp.py",
        "scripts/hosted/seed_acceptance_state.py",
        "scripts/validate-cloud" + "flare-edge",
        "src/thesistrace/auth.py",
        "src/thesistrace/operator.py",
        "src/thesistrace/provisioning.py",
        "src/thesistrace/rate_limits.py",
        "src/thesistrace/tenancy.py",
        "src/thesistrace/hosted/control.py",
        "src/thesistrace/hosted/management.py",
        "src/thesistrace/hosted/schema.sql",
        "src/thesistrace/hosted/provisioning.py",
        "src/thesistrace/hosted/runtime.py",
        "tests/hosted/test_compose_stack.py",
        "tests/hosted/test_container_boundaries.py",
        "tests/hosted/test_daily_track_lifecycle.py",
        "tests/hosted/test_edge_policy.py",
        "tests/hosted/test_edge_rate_limits.py",
        "tests/hosted/test_ins" + "forge_auth.py",
        "tests/hosted/test_registration_provisioning.py",
        "tests/hosted/test_source_authorization.py",
        "tests/hosted/test_workspace_isolation.py",
    )
    for removed_path in removed_paths:
        assert not (ROOT / removed_path).exists()

    active_files = [
        ROOT / ".mise.toml",
        ROOT / "package.json",
        ROOT / "pnpm-workspace.yaml",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ]
    for active_root in (ROOT / "src", ROOT / "scripts", ROOT / "tests", ROOT / "web"):
        active_files.extend(
            path
            for path in active_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and "node_modules" not in path.parts
            and "dist" not in path.parts
            and (
                active_root == ROOT / "scripts"
                or path.suffix in {".json", ".py", ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
            )
        )
    retired_tokens = (
        "ins" + "forge",
        "cloud" + "flare",
        "personal " + "workspace",
        "thesistrace_auth_" + "mode",
        "auth_" + "mode",
        "thesistrace-" + "operator",
        "hosted-" + "up",
        "hosted-" + "deploy",
        "hosted-" + "down",
        "hosted-" + "restart",
        "hosted-" + "smoke",
        "hosted-smtp-" + "configure",
        "hosted-" + "config",
        "hosted-" + "operator",
    )
    for path in active_files:
        source = path.read_text(errors="ignore").lower()
        for token in retired_tokens:
            assert token not in source, f"{token} remains in {path.relative_to(ROOT)}"

    archive = ROOT / "docs" / "archive" / "hosted-v2-pre-core-closure.md"
    archive_source = archive.read_text()
    assert "refs/archive/hosted-v2-pre-core-closure" in archive_source
    assert "Recovery contract" in archive_source

    for obsolete_text in (
        ROOT / "docs" / "archive" / "hosted-compose.md",
        ROOT / "docs" / "archive" / "hosted-health.md",
        ROOT / "docs" / "archive" / "v1-operations.md",
        ROOT
        / "docs"
        / "research"
        / ("2026-08-03-ins" + "forge-use-cases-and-reference-architecture.md"),
        ROOT
        / "docs"
        / "adr"
        / ("0150-separate-ins" + "forge-identity-from-thesistrace-auth-sessions.md"),
    ):
        assert not obsolete_text.exists()

def test_alpha_tree_has_only_normalized_input_and_no_dynamic_execution() -> None:
    alpha_source = (ROOT / "src" / "thesistrace" / "research_kernel" / "alpha.py").read_text()
    normalized_source = (
        ROOT / "src" / "thesistrace" / "research_kernel" / "alpha_expression.py"
    ).read_text()
    assert "ast.parse(" not in alpha_source
    assert "isinstance(expression, str)" not in alpha_source
    assert "type AlphaExpression = str" not in normalized_source
    for forbidden in ("eval(", "exec(", "importlib", "sql"):
        assert forbidden not in normalized_source.lower()


def test_data_owns_the_single_authorable_field_binding_catalog() -> None:
    data_fields = (ROOT / "src" / "thesistrace" / "data" / "fields.py").read_text()
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


def test_publication_runtime_has_one_bounded_request_attempt() -> None:
    class FailingS3Handler(BaseHTTPRequestHandler):
        request_count = 0

        def do_GET(self) -> None:
            type(self).request_count += 1
            payload = b"<Error><Code>InternalError</Code><Message>failed</Message></Error>"
            self.send_response(500)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FailingS3Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = publication_request_config()
    client = boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{server.server_port}",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        region_name="us-east-1",
        config=config,
    )
    try:
        with pytest.raises(ClientError):
            client.list_buckets()
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert PUBLICATION_REQUEST_TIMEOUT_SECONDS == 5.0
    assert config.connect_timeout == config.read_timeout == 5.0
    assert FailingS3Handler.request_count == 1
    assert not thread.is_alive()


def test_publication_owns_its_sql_and_never_commits_a_caller_transaction() -> None:
    service = (ROOT / "src" / "thesistrace" / "publication" / "service.py").read_text()
    schema = (ROOT / "src" / "thesistrace" / "publication" / "schema.sql").read_text()

    assert "CREATE TABLE publication.objects" in schema
    assert "CREATE TABLE publication.manifests" in schema
    assert "CREATE TABLE publication.manifest_objects" in schema
    assert "def record(" in service
    assert "def read_in_transaction(" in service
    assert ".commit(" not in service
    for product_schema in (
        "data.",
        "definitions.",
        "research_runs.",
        "research_batches.",
        "daily_tracks.",
    ):
        assert product_schema not in service
        assert product_schema not in schema


def test_research_run_keeps_direct_admission_behind_one_atomic_sql_seam() -> None:
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    run_schema = (ROOT / "src" / "thesistrace" / "research_run" / "schema.sql").read_text()

    assert "def admit(" in run_source
    assert ".commit(" not in run_source
    assert "CREATE TABLE research_runs.runs" in run_schema
    assert "CREATE TABLE research_runs.admission_requests" in run_schema
    assert "ResearchRunAdmissionCommand" in run_source
    assert "compile_formula(command.formula)" in run_source
    assert not list((ROOT / "src" / "thesistrace" / "definition").glob("*.py"))
    assert not (ROOT / "src" / "thesistrace" / "definition" / "schema.sql").exists()
    assert "definitions." not in run_source
    assert "definitions." not in run_schema


def test_start_tracking_receipts_are_owned_only_by_research_runs() -> None:
    runtime = (ROOT / "src" / "thesistrace" / "entrypoints" / "runtime.py").read_text()
    track = (ROOT / "src" / "thesistrace" / "daily_track" / "service.py").read_text()
    run = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    track_schema = (ROOT / "src" / "thesistrace" / "daily_track" / "schema.sql").read_text()
    run_schema = (ROOT / "src" / "thesistrace" / "research_run" / "schema.sql").read_text()
    track_models = (ROOT / "src" / "thesistrace" / "daily_track" / "models.py").read_text()
    run_models = (ROOT / "src" / "thesistrace" / "research_run" / "models.py").read_text()

    assert "cutover" not in runtime.lower()
    assert "legacy" not in runtime.lower()
    for sql_verb in ("FROM", "JOIN", "INSERT INTO", "UPDATE", "DELETE FROM"):
        assert f"{sql_verb} research_runs." not in runtime
        assert f"{sql_verb} daily_tracks." not in runtime
    assert "INSERT INTO research_runs.start_tracking_receipts" in run
    assert "CREATE TABLE research_runs.start_tracking_receipts" in run_schema
    assert "activation_receipts" not in track
    assert "activation_receipts" not in track_schema
    assert "activation_receipts" not in run_schema
    assert "LegacyStartTrackingReceipt" not in track_models
    assert "StartTrackingCommand" not in track_models
    assert "class StartTrackingCommand" in run_models


def test_research_run_processor_owns_claims_and_uses_module_seams() -> None:
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    failure_policy_source = (
        ROOT / "src" / "thesistrace" / "research_run" / "failure_policy.py"
    ).read_text()
    run_schema = (ROOT / "src" / "thesistrace" / "research_run" / "schema.sql").read_text()
    worker_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "worker.py").read_text()

    assert "def process_next(" in run_source
    assert "FOR UPDATE OF run SKIP LOCKED" in run_source
    assert "CREATE TABLE research_runs.attempts" in run_schema
    assert "execution_fence" in run_schema
    assert "lease_expires_at <= now()" in run_source
    assert "def _maintain_claim(" in run_source
    assert "def _heartbeat_claim(" in run_source
    assert "MAX_RESEARCH_RUN_ATTEMPTS = 3" in failure_policy_source
    assert "attempt_retry_eligible" in run_source
    assert "def _failure_policy(" in run_source
    assert "PublicationUnavailableError" in run_source
    assert "failure_reason text" in run_schema
    assert "def cancel(" in run_source
    assert "CREATE TABLE research_runs.cancel_receipts" in run_schema
    assert "execution_fence = execution_fence + 1" in run_source
    assert "def rerun(" not in run_source
    assert "rerun_receipts" not in run_schema
    assert "compile_formula" not in run_source[run_source.index("    def process_next(") :]
    assert "self._publication.record(" in run_source
    assert "runtime.research_runs.process_next(" in worker_source
    assert "on_claim=claim" in worker_source
    assert "on_execution_event=emit" in worker_source
    assert "while runtime.daily_tracks.process_next" not in worker_source
    for removed in ("outbox", "dispatch", "global job", "temporal"):
        assert removed not in run_source.lower()
        assert removed not in run_schema.lower()
    for foreign_schema in ("data", "definitions", "publication", "daily_tracks"):
        for sql_verb in ("FROM", "JOIN", "INSERT INTO", "UPDATE", "DELETE FROM"):
            assert f"{sql_verb} {foreign_schema}." not in run_source


def test_research_execution_child_has_one_columnar_calculation_route() -> None:
    execution_source = (
        ROOT / "src" / "thesistrace" / "research_run" / "execution.py"
    ).read_text()
    transport_source = (
        ROOT / "src" / "thesistrace" / "research_run" / "supervised_child.py"
    ).read_text()
    service_source = (
        ROOT / "src" / "thesistrace" / "research_run" / "service.py"
    ).read_text()
    compose_source = (ROOT / "deploy" / "core" / "compose.yaml").read_text()
    test_compose_source = (
        ROOT / "deploy" / "core" / "compose.test-run.yaml"
    ).read_text()
    image_smoke_compose_source = (
        ROOT / "deploy" / "core" / "compose.image-smoke.yaml"
    ).read_text()

    assert "read_columnar_slice(" in execution_source
    assert "read_composite_slice(" not in execution_source
    assert "run_kernel(" not in execution_source
    assert "to_pylist(" not in execution_source
    assert "deepcopy(" not in execution_source
    assert "run_kernel(" not in service_source
    assert "canonical-data:/var/lib/thesistrace/canonical-data:ro" in compose_source
    assert "benchmark-data:/var/lib/thesistrace/benchmark-data" in compose_source
    assert compose_source.count(
        "benchmark-data:/var/lib/thesistrace/benchmark-data"
    ) == 2
    assert (
        "batch-attempt-control:/var/lib/thesistrace/.batch-attempts"
        in compose_source
    )
    assert "/canonical-data/.batch-attempts" not in compose_source
    assert ":/var/lib/thesistrace/canonical-data:ro" in test_compose_source
    assert ":/var/lib/thesistrace/benchmark-data" in test_compose_source
    assert test_compose_source.count(":/var/lib/thesistrace/benchmark-data") == 2
    assert (
        ":/var/lib/thesistrace/.batch-attempts" in test_compose_source
    )
    assert "/canonical-data/.batch-attempts" not in test_compose_source
    assert (
        "${THESISTRACE_TEST_BENCHMARK_MOUNT}:/smoke-data/benchmark-data"
        in image_smoke_compose_source
    )
    assert image_smoke_compose_source.count(
        "${THESISTRACE_TEST_BENCHMARK_MOUNT}:/smoke-data/benchmark-data"
    ) == 2
    assert "${THESISTRACE_TEST_RUN_ROOT}:/smoke-data" not in image_smoke_compose_source
    assert "/canonical-data/.batch-attempts" not in image_smoke_compose_source
    child_environment = transport_source[
        transport_source.index("def child_environment(") : transport_source.index(
            "def enforce_cancellation_deadline("
        )
    ]
    for authority in (
        "THESISTRACE_DATABASE_URL",
        "THESISTRACE_S3_ENDPOINT_URL",
        "THESISTRACE_S3_ACCESS_KEY_ID",
        "THESISTRACE_S3_SECRET_ACCESS_KEY",
    ):
        assert authority not in child_environment


def test_tracking_execution_child_has_one_columnar_calculation_route() -> None:
    calculation_source = (
        ROOT / "src" / "thesistrace" / "daily_track" / "calculation.py"
    ).read_text()

    assert "read_columnar_slice(" in calculation_source
    assert "read_composite_slice(" not in calculation_source
    assert "to_pylist(" not in calculation_source
    assert "deepcopy(" not in calculation_source


def test_daily_track_owns_activation_sql_and_copied_origin() -> None:
    track_source = (ROOT / "src" / "thesistrace" / "daily_track" / "service.py").read_text()
    track_schema = (ROOT / "src" / "thesistrace" / "daily_track" / "schema.sql").read_text()
    run_source = (ROOT / "src" / "thesistrace" / "research_run" / "service.py").read_text()
    run_schema = (ROOT / "src" / "thesistrace" / "research_run" / "schema.sql").read_text()
    http_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "http.py").read_text()
    worker_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "worker.py").read_text()

    assert "CREATE TABLE daily_tracks.tracks" in track_schema
    assert "CREATE TABLE daily_tracks.session_progressions" in track_schema
    assert "CREATE TABLE daily_tracks.session_checkpoints" in track_schema
    assert "blocked_progression_id" in track_schema
    assert "CREATE TABLE daily_tracks.retry_receipts" in track_schema
    assert "CREATE TABLE daily_tracks.stop_receipts" in track_schema
    assert "ACTIVE_DAILY_TRACK_LIMIT = 10" in track_source
    assert 'f"daily_tracks.activation.capacity:{researcher_id}"' in track_source
    assert "def _record_current_failure(" in track_source
    assert "def reconcile_working_cache(" in track_source
    assert "def activate(" in track_source
    assert "def resolve_activation(" not in track_source
    assert "origin" in track_source
    assert "activate_track" in run_source
    assert "resolve_track_activation" not in run_source
    assert "CREATE TABLE research_runs.start_tracking_receipts" in run_schema
    activation_source = track_source[
        track_source.index("    def activate(") : track_source.index("    def process_next(")
    ]
    assert "daily_tracks.activation_receipts" not in activation_source
    assert "read_in_transaction" in run_source
    assert "TrackingOrigin(" in run_source
    assert "daily_tracks." not in run_source
    assert "research_runs." not in track_source
    assert (
        "REFERENCES research_runs.run_ownership(researcher_id, run_id)"
        in track_schema
    )
    assert "REFERENCES research_runs.runs" not in track_schema
    for sql_verb in ("FROM", "JOIN", "INSERT INTO", "UPDATE", "DELETE FROM"):
        assert f"{sql_verb} data." not in track_source
    assert 'kind="daily-track.checkpoint"' in track_source
    assert "runtime.daily_tracks.reconcile_working_cache(" in worker_source
    assert 'component="tracking_worker"' in worker_source
    assert 'worker_role="tracking"' in worker_source
    assert '"/api/research-runs/{run_id}/daily-tracks"' in http_source
    assert '"/api/daily-tracks/{track_id}/retry"' in http_source
    assert '"/api/daily-tracks/{track_id}/stop"' in http_source
    assert '@app.post("/api/daily-tracks"' not in http_source
    assert '"/api/daily-tracks/{track_id}"' in http_source
    for legacy_coordinate in (
        "seed_release_id",
        "current_release_id",
        "target_release_id",
        "predecessor_release_id",
        "blocked_target_release_id",
        "next_release",
    ):
        assert legacy_coordinate not in track_source


def test_permanent_runtime_has_only_the_mounted_current_data_path() -> None:
    runtime = (ROOT / "src" / "thesistrace" / "entrypoints" / "runtime.py").read_text()
    worker = (ROOT / "src" / "thesistrace" / "entrypoints" / "worker.py").read_text()
    http = (ROOT / "src" / "thesistrace" / "entrypoints" / "http.py").read_text()
    data_exports = (ROOT / "src" / "thesistrace" / "data" / "__init__.py").read_text()
    assert not (ROOT / "src" / "thesistrace" / "data" / "service.py").exists()
    for source in (runtime, worker, http, data_exports):
        assert "DataService" not in source
        assert "FixtureDataSource" not in source
        assert "TushareDataSource" not in source
        assert "latest_release" not in source
        assert "next_release" not in source
    assert '"/api/data/releases' not in http
    assert '"/api/data/update' not in http


def test_daily_track_working_cache_is_private_concrete_and_worker_local() -> None:
    package = ROOT / "src" / "thesistrace" / "daily_track"
    source = "\n".join(path.read_text() for path in package.rglob("*.py"))
    exported = (package / "__init__.py").read_text()
    http_source = (ROOT / "src" / "thesistrace" / "entrypoints" / "http.py").read_text()

    assert "thesistrace." + "working_cache" not in source
    assert "WorkingCache" + "Port" not in source
    assert "_DailyTrackWorkingCache" not in exported
    assert "working_cache_root" not in CoreSettings.__dataclass_fields__
    assert not (ROOT / "src" / "thesistrace" / "ports.py").exists()
    assert "/api/working-cache" not in http_source


def test_financial_refresh_composes_only_its_prevalidated_candidate() -> None:
    source = (
        ROOT / "src" / "thesistrace" / "data" / "financial_refresh.py"
    ).read_text()

    assert "._compose_prevalidated_financial_candidate(" in source
    assert ".compose_financial_candidate(" not in source


def test_daily_financial_refresh_composes_only_its_prevalidated_candidate() -> None:
    source = (
        ROOT / "src" / "thesistrace" / "data" / "daily_financial_refresh.py"
    ).read_text()

    assert "._compose_prevalidated_financial_candidate(" in source
    assert ".compose_financial_candidate(" not in source


def test_research_kernel_run_has_no_product_or_infrastructure_dependency() -> None:
    package = ROOT / "src" / "thesistrace" / "research_kernel"
    source = "\n".join(path.read_text() for path in package.rglob("*.py"))

    for forbidden in (
        "thesistrace._postgres",
        "thesistrace." + "bounded_research",
        "thesistrace." + "hosted",
        "thesistrace.ports",
        "thesistrace.quota",
        "thesistrace." + "research_runs",
        "thesistrace.storage",
        "boto3",
        "fastapi",
        "httpx",
        "psycopg",
        "temporalio",
    ):
        assert forbidden not in source
    assert "mode:" not in source
    assert "mode =" not in source


def test_importing_research_kernel_does_not_load_infrastructure() -> None:
    script = """
import json
import sys
from thesistrace.research_kernel import RunInput
del RunInput
forbidden = {
    name for name in sys.modules
    if name == "psycopg"
    or name.startswith("psycopg.")
    or name in {"boto3", "fastapi", "httpx", "temporalio"}
    or name.startswith("thesistrace.publication")
    or name in {"thesistrace.objects", "thesistrace.ports"}
}
print(json.dumps(sorted(forbidden)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []


def test_legacy_definition_and_research_run_modules_are_absent() -> None:
    package = ROOT / "src" / "thesistrace"
    for removed in (
        "definitions.py",
        "research_runs.py",
        "bounded_research.py",
        "result_objects.py",
        "resource_deletion.py",
        "config.py",
        "runtime.py",
        "storage.py",
        "worker.py",
        "objects.py",
        "ports.py",
        "management.py",
        "activity_contract.py",
        "alpha.py",
        "factor.py",
        "strategy.py",
        "numeric.py",
    ):
        assert not (package / removed).exists()

    assert not (package / "api.py").exists()
    assert not list((package / "definition").glob("*.py"))
    assert not (package / "definition" / "schema.sql").exists()


def test_obsolete_authoring_contract_cannot_reenter_the_active_runtime() -> None:
    package = ROOT / "src" / "thesistrace"
    http_source = (package / "entrypoints" / "http.py").read_text()
    entrypoint_source = "\n".join(
        path.read_text() for path in (package / "entrypoints").glob("*.py")
    )
    schema_source = (package / "entrypoints" / "schema.py").read_text()
    worker_source = (package / "entrypoints" / "worker.py").read_text()
    web_source = "\n".join(
        path.read_text()
        for path in (ROOT / "web" / "src").rglob("*")
        if path.suffix in {".ts", ".tsx", ".css"} and ".test." not in path.name
    )

    assert '"research_folders"' in schema_source
    assert '"researchers"' in schema_source
    assert '"definitions"' not in schema_source
    assert "/api/definitions" not in entrypoint_source
    assert "/rerun" not in entrypoint_source
    assert "compile_formula" not in worker_source
    assert "/definitions" not in web_source
    assert "definition-list" not in web_source
    assert not (package / "migrations").exists()
    assert not (ROOT / "migrations").exists()

    active_authoring = "\n".join(
        (
            http_source,
            schema_source,
            (package / "research_run" / "models.py").read_text(),
            (package / "research_run" / "schema.sql").read_text(),
        )
    ).lower()
    for forbidden in (
        "revision_id",
        "rerun_receipts",
        "compatibility endpoint",
        "definition_id",
        "alpha_release_id",
    ):
        assert forbidden not in active_authoring


def test_browser_only_plots_backend_precomputed_strategy_comparison_curves() -> None:
    web_root = ROOT / "web" / "src"
    chart_source = (web_root / "analysis" / "StrategyPerformanceChart.tsx").read_text()
    product_source = "\n".join(
        path.read_text()
        for path in web_root.rglob("*")
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    )

    for precomputed_field in (
        "net_strategy_return",
        "benchmark_relative_return",
    ):
        assert precomputed_field in chart_source
    for forbidden_financial_input in (
        "net_nav",
        "benchmark_nav",
        "initial_cash_cny",
        "benchmark_open_level",
        "net_excess_nav",
    ):
        assert forbidden_financial_input not in chart_source
    assert "selected_universe_equal_weight" not in product_source
    assert "benchmark_nav" not in product_source



def _string_literals(path: Path) -> str:
    tree = ast.parse(path.read_text())
    return "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _internal_dependencies(path: Path, tree: ast.AST) -> set[str]:
    root = ROOT / "src" / "thesistrace"
    package_parts = ["thesistrace", *path.relative_to(root).parent.parts]
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        targets: list[list[str]] = []
        if isinstance(node, ast.Import):
            targets.extend(alias.name.split(".") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                if node.module:
                    targets.append([*base, *node.module.split(".")])
                else:
                    targets.extend([*base, alias.name] for alias in node.names)
            elif node.module == "thesistrace":
                targets.extend(["thesistrace", alias.name] for alias in node.names)
            elif node.module:
                targets.append(node.module.split("."))
        dependencies.update(
            target[1]
            for target in targets
            if len(target) > 1 and target[0] == "thesistrace"
        )
    return dependencies


def _assert_acyclic(graph: dict[str, set[str]]) -> None:
    visited: set[str] = set()
    visiting: list[str] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        assert node not in visiting, f"Core import cycle: {' -> '.join([*visiting, node])}"
        visiting.append(node)
        for dependency in sorted(graph[node]):
            visit(dependency)
        visiting.pop()
        visited.add(node)

    for node in sorted(graph):
        visit(node)


def _http_routes() -> set[tuple[str, str]]:
    inventory: set[tuple[str, str]] = set()
    for route in create_app().routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") and path != "/api":
            continue
        methods = getattr(route, "methods", None)
        assert methods is not None, f"mounted or non-HTTP Core route is not allowed: {path}"
        product_methods = set(methods) - {"HEAD", "OPTIONS"}
        assert product_methods, f"Core route has no explicit product method: {path}"
        inventory.update((method.lower(), path) for method in product_methods)
    return inventory


def _package_script(name: str) -> str:
    package = json.loads((ROOT / "package.json").read_text())
    return package["scripts"][name]
