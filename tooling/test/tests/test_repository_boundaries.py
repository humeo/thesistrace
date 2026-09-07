import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_current_runtime_initializes_before_starting_long_running_processes() -> None:
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    initialize_service = compose.split("  initialize:\n", maxsplit=1)[1].split(
        "  api:\n", maxsplit=1
    )[0]
    api_service = compose.split("  api:\n", maxsplit=1)[1].split(
        "  research-worker:\n", maxsplit=1
    )[0]
    research_worker = compose.split("  research-worker:\n", maxsplit=1)[1].split(
        "  batch-research-worker:\n", maxsplit=1
    )[0]
    batch_research_worker = compose.split("  batch-research-worker:\n", maxsplit=1)[1].split(
        "  tracking-worker:\n", maxsplit=1
    )[0]
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


def test_canonical_compose_pins_external_infrastructure_images() -> None:
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "postgres:16.10-alpine" in compose
    assert "rustfs/rustfs:1.0.0-beta.12" in compose
    assert ":latest" not in compose
    for forbidden in ("sqlite", "temporal", "object-store"):
        assert forbidden not in compose.lower()
    assert "  auth-initialize:\n" in compose
    assert "  auth:\n" in compose


def test_web_shell_declares_only_the_four_product_resources() -> None:
    source = (ROOT / "apps/web" / "src" / "shell" / "AppShell.tsx").read_text()
    main = (ROOT / "apps/web" / "src" / "main.tsx").read_text()
    package = json.loads((ROOT / "apps/web" / "package.json").read_text())
    browser = (ROOT / "tests" / "playwright.config.ts").read_text()
    vite = (ROOT / "apps/web" / "vite.config.ts").read_text()
    core_app = (ROOT / "apps/web" / "src" / "shell" / "CoreApp.tsx").read_text()
    resource_routes = source.partition("const resourceRoutes = [")[2].partition("] as const;")[0]
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
    assert set(package["scripts"]) == {
        "build",
        "dev",
        "test:browser",
        "test:shell",
        "typecheck",
    }
    assert "THESISTRACE_TEST_WEB_ORIGIN" in browser
    assert "THESISTRACE_TEST_EVIDENCE_DIR" in browser
    assert "retain-on-failure" in browser
    assert "noSnippets: true" in browser
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
        assert not (ROOT / "apps/web" / removed_path).exists()


def test_default_gate_excludes_deferred_and_credential_dependent_work() -> None:
    core_gate = _package_script("check")
    live_gate = _package_script("check:live-tushare")

    assert core_gate == "pnpm test && pnpm test:browser && pnpm test:integration && pnpm test:e2e"
    for deferred in (
        "hosted",
        "login",
        "deploy",
        "sqlite",
        "check-live-tushare",
        "check_live_tushare",
    ):
        assert deferred not in core_gate.lower()
    assert live_gate == (
        "node tooling/config/cli.mjs run uv run --project apps/core python "
        "apps/core/tools/check_live_tushare.py"
    )


def test_fast_host_gate_uses_bounded_parallelism_without_expensive_work() -> None:
    assert _package_script("test") == "node tooling/test/quick.mjs"
    completed = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            (
                "import {quickCommands} from './tooling/test/suites.mjs'; "
                "console.log(JSON.stringify(quickCommands))"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    fast_gate = "\n".join(
        " ".join([command, *args]) for command, args in json.loads(completed.stdout)
    )

    for command in (
        "uv run --project apps/core ruff check --config apps/core/pyproject.toml",
        "--rootdir . -q -n 4 apps/core/tests/kernel apps/core/tests/architecture",
        "pnpm --dir apps/web typecheck",
        "pnpm --dir apps/web test:shell",
    ):
        assert command in fast_gate
    for excluded in (
        "docker",
        "compose",
        "core-test-runtime",
        "test-runtime",
        "tests/integration",
        "tests/acceptance",
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
        "apps/core/src/thesistrace/hosted",
        "tests/hosted",
        "scripts/hosted-stack",
        "scripts/hosted-auth-smoke.py",
        "scripts/hosted-release-smoke.py",
        "scripts/hosted-" + "smoke.py",
        "scripts/hosted/configure_smtp.py",
        "scripts/hosted/seed_acceptance_state.py",
        "scripts/validate-cloud" + "flare-edge",
        "apps/core/src/thesistrace/auth.py",
        "apps/core/src/thesistrace/operator.py",
        "apps/core/src/thesistrace/provisioning.py",
        "apps/core/src/thesistrace/rate_limits.py",
        "apps/core/src/thesistrace/tenancy.py",
        "apps/core/src/thesistrace/hosted/control.py",
        "apps/core/src/thesistrace/hosted/management.py",
        "apps/core/src/thesistrace/hosted/schema.sql",
        "apps/core/src/thesistrace/hosted/provisioning.py",
        "apps/core/src/thesistrace/hosted/runtime.py",
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
        ROOT / "apps/core/pyproject.toml",
        ROOT / "apps/core/uv.lock",
    ]
    for active_root in (
        ROOT / "apps/core" / "src",
        ROOT / "tooling",
        ROOT / "tests",
        ROOT / "apps/web",
    ):
        active_files.extend(
            path
            for path in active_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and "node_modules" not in path.parts
            and "dist" not in path.parts
            and (
                active_root == ROOT / "tooling"
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


def _package_script(name: str) -> str:
    package = json.loads((ROOT / "package.json").read_text())
    return package["scripts"][name]
