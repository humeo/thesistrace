from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from production_configuration_fixtures import VALID_ENVIRONMENT, _run

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ["node", ROOT / "tooling/dev/runtime.mjs", "production"]


def test_production_runtime_validates_before_rendering_or_starting(
    tmp_path: Path,
) -> None:
    environment_file = tmp_path / "production.env"
    environment_file.write_text(VALID_ENVIRONMENT)
    environment_file.chmod(0o600)
    command_log = tmp_path / "docker.log"
    completed = _run(
        tmp_path,
        environment_file,
        "up",
        stat_result="0:600",
        command_log=command_log,
    )

    assert completed.returncode == 0, completed.stderr
    commands = command_log.read_text().splitlines()
    assert len(commands) == 2
    assert "config --quiet" in commands[0]
    assert "up --detach --build --wait --wait-timeout 300" in commands[1]
    assert all("--env-file" in command for command in commands)
    assert "OwnerRuntime" not in command_log.read_text()
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_production_runtime_prevents_ambient_security_overrides(
    tmp_path: Path,
) -> None:
    environment_file = tmp_path / "production.env"
    environment_file.write_text(VALID_ENVIRONMENT)
    environment_file.chmod(0o600)
    environment_log = tmp_path / "docker-environment.log"

    completed = _run(
        tmp_path,
        environment_file,
        "validate",
        stat_result="0:600",
        environment_log=environment_log,
        ambient_overrides={
            "BETTER_AUTH_SECRET": "ambient-secret-must-not-override",
            "THESISTRACE_AGENT_MODEL_REGISTRY": "ambient-registry-must-not-override",
            "THESISTRACE_AGENT_OPENAI_API_KEY": "ambient-provider-must-not-override",
            "THESISTRACE_MCP_SIGNING_PRIVATE_JWK": "ambient-private-key-must-not-override",
            "THESISTRACE_PUBLIC_ORIGIN": "http://ambient.invalid",
            "THESISTRACE_TUSHARE_TOKEN": "ambient-token-must-not-override",
        },
    )

    assert completed.returncode == 0, completed.stderr
    lines = environment_log.read_text().splitlines()
    assert json.loads(lines[3].removeprefix("agent_registry=")) == json.loads(
        (ROOT / "config" / "model-registry.json").read_text()
    )
    assert lines[:3] + lines[4:] == [
        "public_origin=https://research.thesistrace.com",
        "auth_secret=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "tushare_token=production-tushare-token-7Kp4mN9vQ2sL6xT8",
        "agent_provider=sk-production-agent-7Kp4mN9vQ2sL6xT8",
        "mcp_private_key="
        + next(
            line.split("=", 1)[1]
            for line in VALID_ENVIRONMENT.splitlines()
            if line.startswith("THESISTRACE_MCP_SIGNING_PRIVATE_JWK=")
        ),
    ]


@pytest.mark.parametrize("metadata", ["501:600", "0:640"])
def test_production_runtime_rejects_non_root_or_non_0600_environment(
    tmp_path: Path,
    metadata: str,
) -> None:
    environment_file = tmp_path / "production.env"
    environment_file.write_text(VALID_ENVIRONMENT)
    environment_file.chmod(0o600)
    completed = _run(tmp_path, environment_file, "up", stat_result=metadata)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["code"] == "PRODUCTION_ENV_FILE_PERMISSIONS_INVALID"


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        (
            "THESISTRACE_ENVIRONMENT=test",
            "CONFIG_ENVIRONMENT_INVALID",
        ),
        (
            "THESISTRACE_PUBLIC_ORIGIN=http://127.0.0.1:5173",
            "PRODUCTION_PUBLIC_ORIGIN_INVALID",
        ),
        (
            "THESISTRACE_PUBLIC_ORIGIN=https://thesistrace.test",
            "PRODUCTION_PUBLIC_ORIGIN_INVALID",
        ),
        (
            "THESISTRACE_PUBLIC_ORIGIN=https://research.thesistrace.com:8443",
            "PRODUCTION_PUBLIC_ORIGIN_INVALID",
        ),
        (
            "THESISTRACE_RESEND_API_URL=http://resend-fake:8300",
            "PRODUCTION_RESEND_URL_INVALID",
        ),
        (
            "THESISTRACE_CORE_DATABASE_PASSWORD=password",
            "PRODUCTION_DATABASE_PASSWORD_INVALID",
        ),
        (
            "THESISTRACE_S3_SECRET_ACCESS_KEY=rustfsadmin",
            "PRODUCTION_STORAGE_CREDENTIAL_INVALID",
        ),
        (
            "THESISTRACE_AGENT_OPENAI_BASE_URL=https://user:secret@provider.test/v1",
            "PRODUCTION_AGENT_BASE_URL_INVALID",
        ),
        (
            "BETTER_AUTH_SECRET=development-only-auth-secret-with-at-least-32-characters",
            "PRODUCTION_AUTH_SECRET_INVALID",
        ),
        (
            "RESEND_API_KEY=resend-test-key",
            "PRODUCTION_RESEND_KEY_INVALID",
        ),
        (
            "THESISTRACE_TUSHARE_TOKEN=development-data-operator-token",
            "CONFIG_CREDENTIAL_INVALID",
        ),
        (
            "THESISTRACE_TUSHARE_TOKEN=<production-tushare-token>",
            "CONFIG_CREDENTIAL_INVALID",
        ),
        (
            "THESISTRACE_AUTH_IMAGE=registry.example:5000/thesistrace/auth",
            "PRODUCTION_AUTH_IMAGE_INVALID",
        ),
        (
            "THESISTRACE_AUTH_IMAGE=ghcr.io/thesistrace/auth:latest",
            "PRODUCTION_AUTH_IMAGE_INVALID",
        ),
        (
            "THESISTRACE_AGENT_IMAGE=registry.example:5000/thesistrace/agent",
            "PRODUCTION_AGENT_IMAGE_INVALID",
        ),
        (
            "THESISTRACE_AGENT_IMAGE=ghcr.io/thesistrace/agent:latest",
            "PRODUCTION_AGENT_IMAGE_INVALID",
        ),
        (
            "THESISTRACE_AGENT_MODEL_REGISTRY=not-json",
            "CONFIG_VARIABLE_UNKNOWN",
        ),
        (
            "THESISTRACE_AGENT_OPENAI_API_KEY=test-provider-key",
            "PRODUCTION_AGENT_PROVIDER_SECRET_INVALID",
        ),
        (
            "THESISTRACE_MCP_RESOURCE_URL=https://research.thesistrace.com/mcp/v1",
            "CONFIG_VARIABLE_UNKNOWN",
        ),
        (
            'THESISTRACE_MCP_AGENT_SCOPES=["research:read"]',
            "PRODUCTION_MCP_SCOPE_INVALID",
        ),
        (
            'THESISTRACE_MCP_DEPLOYMENT_TOOLS=["get_research_context"]',
            "PRODUCTION_MCP_TOOL_SET_INVALID",
        ),
        (
            'THESISTRACE_MCP_ALLOWED_HOSTS=["api:8100"]',
            "CONFIG_VARIABLE_UNKNOWN",
        ),
        (
            "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS=630",
            "CONFIG_MCP_TIME_BUDGET_INVALID",
        ),
        (
            'THESISTRACE_MCP_VERIFYING_PUBLIC_JWK={"alg":"EdDSA"}',
            "PRODUCTION_MCP_SIGNING_KEY_INVALID",
        ),
    ],
)
def test_production_runtime_rejects_test_placeholder_and_weak_values(
    tmp_path: Path,
    replacement: str,
    code: str,
) -> None:
    key = replacement.split("=", maxsplit=1)[0]
    source = (
        "\n".join(
            replacement if line.startswith(f"{key}=") else line
            for line in VALID_ENVIRONMENT.splitlines()
        )
        + "\n"
    )
    if not any(line.startswith(f"{key}=") for line in VALID_ENVIRONMENT.splitlines()):
        source += replacement + "\n"
    environment_file = tmp_path / "production.env"
    environment_file.write_text(source)
    environment_file.chmod(0o600)
    completed = _run(tmp_path, environment_file, "up", stat_result="0:600")

    assert completed.returncode == 2
    assert code in completed.stderr
    assert replacement.split("=", maxsplit=1)[1] not in completed.stderr


def test_production_runtime_rejects_relative_in_repository_and_duplicate_files(
    tmp_path: Path,
) -> None:
    relative = subprocess.run(
        [*SCRIPT, "up"],
        cwd=ROOT,
        env={**os.environ, "THESISTRACE_ENV_FILE": "production.env"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert relative.returncode == 2
    assert "PRODUCTION_ENV_FILE_PATH_INVALID" in relative.stderr

    repository = _run(
        tmp_path,
        ROOT / ".env.example",
        "up",
        stat_result="0:600",
    )
    assert repository.returncode == 2
    assert "PRODUCTION_ENV_FILE_PATH_INVALID" in repository.stderr

    duplicated = tmp_path / "duplicate.env"
    duplicated.write_text(VALID_ENVIRONMENT + "RESEND_API_KEY=re_duplicate_key_123456789\n")
    duplicated.chmod(0o600)
    duplicate = _run(tmp_path, duplicated, "up", stat_result="0:600")
    assert duplicate.returncode == 2
    assert "CONFIG_VARIABLE_DUPLICATED" in duplicate.stderr
