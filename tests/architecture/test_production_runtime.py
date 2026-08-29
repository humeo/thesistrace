from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "production-runtime"

VALID_AGENT_REGISTRY = (
    '{"default_model_key":"openai-research","models":['
    '{"default_reasoning_effort":"medium","display_name":"OpenAI Research",'
    '"enabled":true,"key":"openai-research","provider_adapter":"openai",'
    '"provider_model_id":"gpt-research",'
    '"reasoning_efforts":["low","medium","high"],'
    '"secret_env":"THESISTRACE_AGENT_OPENAI_API_KEY"}]}'
)

VALID_ENVIRONMENT = f"""\
THESISTRACE_ENVIRONMENT=production
THESISTRACE_PUBLIC_ORIGIN=https://research.thesistrace.com
THESISTRACE_RESEND_API_URL=https://api.resend.com
THESISTRACE_OWNER_DATABASE_PASSWORD=OwnerRuntime_7Qh9tT4Sx2Vk8Lm3
THESISTRACE_CORE_DATABASE_PASSWORD=CoreRuntime_3Nm8qW6Zp5Jc2Rs7
THESISTRACE_AUTH_DATABASE_PASSWORD=AuthRuntime_9Fd4vB7Ky2Hg6Px8
THESISTRACE_AGENT_DATABASE_PASSWORD=AgentRuntime_5Jt8mQ3Wx7Lc9Vr4
BETTER_AUTH_SECRET=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
RESEND_API_KEY=re_production_7Kp4mN9vQ2sL6xT8
RESEND_FROM_EMAIL=ThesisTrace <noreply@thesistrace.com>
THESISTRACE_AUTH_IMAGE=ghcr.io/thesistrace/auth:2026-08-29
THESISTRACE_AGENT_IMAGE=ghcr.io/thesistrace/agent:2026-08-29
THESISTRACE_AGENT_BUILD_REVISION=2026-08-29.1
THESISTRACE_AGENT_MODEL_REGISTRY={VALID_AGENT_REGISTRY}
THESISTRACE_AGENT_OPENAI_API_KEY=sk-production-agent-7Kp4mN9vQ2sL6xT8
"""


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
    assert "up --detach --wait --build" in commands[1]
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
            "THESISTRACE_PUBLIC_ORIGIN": "http://ambient.invalid",
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert environment_log.read_text().splitlines() == [
        "public_origin=unset",
        "auth_secret=unset",
        "agent_registry=unset",
        "agent_provider=unset",
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
    assert completed.stderr == (
        '{"code":"PRODUCTION_ENV_FILE_PERMISSIONS_INVALID",'
        '"event":"production_runtime_failed"}\n'
    )


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        (
            "THESISTRACE_ENVIRONMENT=test",
            "PRODUCTION_ENVIRONMENT_INVALID",
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
            "BETTER_AUTH_SECRET=development-only-auth-secret-with-at-least-32-characters",
            "PRODUCTION_AUTH_SECRET_INVALID",
        ),
        (
            "RESEND_API_KEY=resend-test-key",
            "PRODUCTION_RESEND_KEY_INVALID",
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
            "PRODUCTION_AGENT_MODEL_REGISTRY_INVALID",
        ),
        (
            "THESISTRACE_AGENT_OPENAI_API_KEY=test-provider-key",
            "PRODUCTION_AGENT_PROVIDER_SECRET_INVALID",
        ),
    ],
)
def test_production_runtime_rejects_test_placeholder_and_weak_values(
    tmp_path: Path,
    replacement: str,
    code: str,
) -> None:
    key = replacement.split("=", maxsplit=1)[0]
    source = "\n".join(
        replacement if line.startswith(f"{key}=") else line
        for line in VALID_ENVIRONMENT.splitlines()
    ) + "\n"
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
        [SCRIPT, "up"],
        cwd=ROOT,
        env={**os.environ, "THESISTRACE_PRODUCTION_ENV_FILE": "production.env"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert relative.returncode == 2
    assert "PRODUCTION_ENV_FILE_PATH_INVALID" in relative.stderr

    repository = _run(
        tmp_path,
        ROOT / "deploy" / "core" / "dev.env",
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
    assert "PRODUCTION_ENV_FILE_CONTENT_INVALID" in duplicate.stderr


def _run(
    tmp_path: Path,
    environment_file: Path,
    action: str,
    *,
    stat_result: str,
    command_log: Path | None = None,
    environment_log: Path | None = None,
    ambient_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stat = bin_dir / "stat"
    stat.write_text(f"#!/bin/sh\nprintf '%s\\n' '{stat_result}'\n")
    stat.chmod(0o755)
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ -n \"${PRODUCTION_RUNTIME_ENV_LOG-}\" ]; then\n"
        "  printf 'public_origin=%s\\nauth_secret=%s\\n' "
        "\"${THESISTRACE_PUBLIC_ORIGIN-unset}\" "
        "\"${BETTER_AUTH_SECRET-unset}\" >>\"$PRODUCTION_RUNTIME_ENV_LOG\"\n"
        "  printf 'agent_registry=%s\\nagent_provider=%s\\n' "
        "\"${THESISTRACE_AGENT_MODEL_REGISTRY-unset}\" "
        "\"${THESISTRACE_AGENT_OPENAI_API_KEY-unset}\" >>\"$PRODUCTION_RUNTIME_ENV_LOG\"\n"
        "fi\n"
        "if [ -n \"${PRODUCTION_RUNTIME_COMMAND_LOG-}\" ]; then\n"
        "  printf '%s\\n' \"docker $*\" >>\"$PRODUCTION_RUNTIME_COMMAND_LOG\"\n"
        "fi\n"
    )
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "THESISTRACE_PRODUCTION_ENV_FILE": str(environment_file),
    }
    if command_log is not None:
        environment["PRODUCTION_RUNTIME_COMMAND_LOG"] = str(command_log)
    if environment_log is not None:
        environment["PRODUCTION_RUNTIME_ENV_LOG"] = str(environment_log)
    if ambient_overrides is not None:
        environment.update(ambient_overrides)
    return subprocess.run(
        [SCRIPT, action],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
