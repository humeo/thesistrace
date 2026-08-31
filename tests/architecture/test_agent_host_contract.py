from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
DEPLOY = ROOT / "deploy" / "core"


def _service(source: str, name: str, next_name: str) -> str:
    return source.split(f"\n  {name}:\n", maxsplit=1)[1].split(
        f"\n  {next_name}:\n", maxsplit=1
    )[0]


def test_agent_host_is_a_private_node_package_without_research_authority() -> None:
    package = json.loads((AGENT / "package.json").read_text())
    dependencies = set(package["dependencies"])
    source = "\n".join(
        path.read_text()
        for path in sorted((AGENT / "src").glob("*.ts"))
        if not path.name.endswith(".test.ts")
    )

    assert package["name"] == "thesistrace-agent-host"
    assert dependencies == {
        "@ag-ui/client",
        "@ag-ui/core",
        "@ag-ui/encoder",
        "@ag-ui/mastra",
        "@ai-sdk/anthropic",
        "@ai-sdk/google",
        "@ai-sdk/openai",
        "@ai-sdk/provider",
        "@copilotkit/runtime",
        "@hono/node-server",
        "@mastra/core",
        "@mastra/memory",
        "@mastra/mcp",
        "@mastra/pg",
        "ai",
        "exit-hook",
        "tokenx",
        "hono",
        "pg",
        "rxjs",
        "zod",
    }
    for forbidden_dependency in ("postgres", "redis", "rustfs", "celery"):
        assert forbidden_dependency not in dependencies
    for forbidden_import in (
        "from thesistrace",
        "import thesistrace",
        "../src/",
        "canonical-data",
        "RustFS",
    ):
        assert forbidden_import not in source


def test_agent_telemetry_has_no_content_store_or_framework_trace_exporter() -> None:
    telemetry = (AGENT / "src" / "run-telemetry.ts").read_text()
    runtime = (AGENT / "src" / "research-runtime.ts").read_text()
    mcp = (AGENT / "src" / "mcp-run.ts").read_text()
    assert "logger: noopLogger" in runtime
    assert "client.__setLogger(noopLogger)" in mcp
    assert "enableServerLogs: false" in mcp
    assert 'import { write } from "node:fs"' in telemetry
    for forbidden in (
        "console.",
        "query(",
        "INSERT ",
        "UPDATE ",
        "saveMessages",
        "span.set",
        "JSON.stringify(error",
    ):
        assert forbidden not in telemetry
    workspace = (ROOT / "pnpm-workspace.yaml").read_text()
    assert "'@ag-ui/mastra@1.1.1': patches/@ag-ui__mastra@1.1.1.patch" in workspace
    for image in ("agent", "auth", "web"):
        dockerfile = (DEPLOY / f"Dockerfile.{image}").read_text()
        assert dockerfile.index("COPY patches ./patches") < dockerfile.index(
            "pnpm install --frozen-lockfile"
        )


def test_agent_compose_identity_receives_only_provider_and_process_configuration() -> None:
    compose = (DEPLOY / "compose.yaml").read_text()
    agent = _service(compose, "agent", "agent-initialize")
    initializer = _service(compose, "agent-initialize", "initialize")

    assert "dockerfile: deploy/core/Dockerfile.agent" in compose
    assert "THESISTRACE_AUTH_INTERNAL_ORIGIN: http://auth:8200" in agent
    assert "THESISTRACE_AGENT_MODEL_REGISTRY" in agent
    assert "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS" in agent
    assert "THESISTRACE_MCP_CLOCK_SKEW_SECONDS" in agent
    assert "THESISTRACE_MCP_INTERNAL_URL: http://api:8100/mcp" in agent
    assert 'COPILOTKIT_TELEMETRY_DISABLED: "true"' in agent
    assert "postgresql://agent_runtime:" in agent
    for provider_secret in (
        "THESISTRACE_AGENT_ANTHROPIC_API_KEY",
        "THESISTRACE_AGENT_GOOGLE_API_KEY",
        "THESISTRACE_AGENT_OPENAI_API_KEY",
        "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
    ):
        assert provider_secret in agent
    for forbidden_credential in (
        "THESISTRACE_DATABASE_URL",
        "THESISTRACE_AUTH_DATABASE_URL",
        "THESISTRACE_OWNER_DATABASE_URL",
        "THESISTRACE_S3_",
        "BETTER_AUTH_SECRET",
        "THESISTRACE_DATA_MOUNT",
        "THESISTRACE_BENCHMARK_MOUNT",
        "QUEUE",
        "WORKER",
        "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS",
        "THESISTRACE_MCP_AGENT_SCOPES",
        "THESISTRACE_MCP_CLIENT_ID",
        "THESISTRACE_MCP_DEPLOYMENT_TOOLS",
        "THESISTRACE_MCP_ISSUER_URL",
        "THESISTRACE_MCP_RESOURCE_URL",
        "THESISTRACE_MCP_SIGNING_PRIVATE_JWK",
        "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK",
    ):
        assert forbidden_credential not in agent
    assert "    ports:\n" not in agent
    assert "THESISTRACE_OWNER_DATABASE_URL" in initializer
    assert "THESISTRACE_AGENT_DATABASE_URL" not in initializer
    assert "THESISTRACE_AGENT_MODEL_REGISTRY" not in initializer
    assert "THESISTRACE_AUTH_INTERNAL_ORIGIN" not in initializer
    assert "THESISTRACE_MCP_" not in initializer


def test_agent_fault_proxies_are_test_only_compose_boundaries() -> None:
    production = (DEPLOY / "compose.yaml").read_text()
    test_overlay = (DEPLOY / "compose.test-run.yaml").read_text()

    assert "auth-exchange-proxy" not in production
    assert "mcp-fault-proxy" not in production
    assert "THESISTRACE_AUTH_INTERNAL_ORIGIN: http://auth:8200" in production
    assert "THESISTRACE_MCP_INTERNAL_URL: http://api:8100/mcp" in production

    assert (
        "THESISTRACE_AUTH_INTERNAL_ORIGIN: http://auth-exchange-proxy:8250"
        in test_overlay
    )
    assert (
        "THESISTRACE_MCP_INTERNAL_URL: http://mcp-fault-proxy:8150/mcp"
        in test_overlay
    )
    assert "../../auth/test-fixtures:/test-fixtures:ro" in test_overlay
    assert "../../agent/test-fixtures:/test-fixtures:ro" in test_overlay


def test_browser_bundle_source_has_no_provider_or_mcp_credential_contract() -> None:
    source = "\n".join(
        path.read_text()
        for path in sorted((ROOT / "web" / "src").rglob("*"))
        if path.is_file()
    )

    for forbidden in (
        "THESISTRACE_AGENT_OPENAI_API_KEY",
        "THESISTRACE_AGENT_ANTHROPIC_API_KEY",
        "THESISTRACE_AGENT_GOOGLE_API_KEY",
        "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
        "provider-secret-value-canary",
        "OAuth access token",
        "THESISTRACE_MCP_",
    ):
        assert forbidden not in source


def test_research_chat_uses_copilotkit_public_headless_boundary() -> None:
    chat_page = (ROOT / "web" / "src" / "chat" / "ChatPage.tsx").read_text()
    provider = (
        ROOT / "web" / "src" / "chat" / "ResearchChatCopilotProvider.tsx"
    ).read_text()

    assert 'from "@copilotkit/react-core/v2/headless"' in chat_page
    assert 'from "@copilotkit/react-core/v2"' not in chat_page
    assert 'from "@copilotkit/react-core/v2/context"' in provider
    assert 'from "@copilotkit/react-core/v2"' not in provider
    assert 'runtimeTransport: "rest"' in provider
    assert 'runtimeUrl: RESEARCH_CHAT_RUNTIME_URL' in provider


def test_agent_startup_logging_cannot_serialize_configuration_details() -> None:
    server = (AGENT / "src" / "server.ts").read_text()

    catch = server.split("main().catch", maxsplit=1)[1]
    assert "AGENT_STARTUP_INVALID" in catch
    assert "agent_startup_failed" in catch
    assert "error" not in catch
    assert "stack" not in catch
    assert "message" not in catch
