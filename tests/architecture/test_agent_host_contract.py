from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
DEPLOY = ROOT / "deploy" / "core"


def _service(source: str, name: str, next_name: str) -> str:
    return source.split(f"  {name}:\n", maxsplit=1)[1].split(
        f"  {next_name}:\n", maxsplit=1
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
    assert dependencies == {"@hono/node-server", "hono", "zod"}
    for forbidden_dependency in ("pg", "postgres", "redis", "rustfs", "celery"):
        assert forbidden_dependency not in dependencies
    for forbidden_import in (
        "thesistrace.",
        "../src/",
        "research_run",
        "canonical-data",
        "RustFS",
    ):
        assert forbidden_import not in source


def test_agent_compose_identity_receives_only_provider_and_process_configuration() -> None:
    compose = (DEPLOY / "compose.yaml").read_text()
    agent = _service(compose, "agent", "initialize")

    assert "dockerfile: deploy/core/Dockerfile.agent" in compose
    assert "THESISTRACE_AUTH_INTERNAL_ORIGIN: http://auth:8200" in agent
    assert "THESISTRACE_AGENT_MODEL_REGISTRY" in agent
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
    ):
        assert forbidden_credential not in agent
    assert "    ports:\n" not in agent


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
    ):
        assert forbidden not in source


def test_agent_startup_logging_cannot_serialize_configuration_details() -> None:
    server = (AGENT / "src" / "server.ts").read_text()

    catch = server.split("main().catch", maxsplit=1)[1]
    assert "AGENT_STARTUP_INVALID" in catch
    assert "agent_startup_failed" in catch
    assert "error" not in catch
    assert "stack" not in catch
    assert "message" not in catch
